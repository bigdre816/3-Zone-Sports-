"""Cloudflare Stream live-input adapter. Stdlib HTTP only.

A direct signed HLS URL can remain usable until its short token expires and
already-buffered segments may continue briefly. Immediate segment-level
revocation requires a later edge authorization Worker; this adapter does not
pretend the manifest URL is an instantaneous kill switch.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request

from .base import AnalyticsSnapshot, ProviderStatus, ProvisionResult, WebhookEvent
from .demo import live_input_create_body

API = "https://api.cloudflare.com/client/v4"


def _redact(text: str) -> str:
    lowered = text.lower()
    if "authorization" in lowered or "streamkey" in lowered or "stream_key" in lowered:
        return "[redacted]"
    return text[:300]


class CloudflareProvider:
    name = "cloudflare"

    def __init__(self, config, opener=None):
        self.config = config
        self._opener = opener  # injectable for tests; default urllib

    def _headers(self) -> dict:
        return {
            "Authorization": "Bearer " + self.config.cf_api_token,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = API + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            if self._opener:
                resp = self._opener(req)
                raw = resp.read() if hasattr(resp, "read") else resp
                return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError("cloudflare request failed: " + _redact(str(exc))) from None
        except urllib.error.URLError as exc:
            raise RuntimeError("cloudflare unreachable") from None

    def provision(self, event: dict) -> ProvisionResult:
        body = live_input_create_body(
            event,
            allowed_origins=self.config.cf_allowed_origins or self.config.allowed_origins,
            delete_after_days=self.config.cf_delete_recording_after_days,
            prefer_low_latency=self.config.cf_prefer_low_latency,
        )
        result = self._request("POST", f"/accounts/{self.config.cf_account_id}/stream/live_inputs", body)
        result_body = result.get("result") or result
        rtmps = result_body.get("rtmps") or {}
        return ProvisionResult(
            input_id=result_body.get("uid") or result_body.get("id"),
            ingest_url=rtmps.get("url") or result_body.get("rtmpsUrl") or "",
            stream_key=rtmps.get("streamKey") or result_body.get("rtmpsKey") or "",
            state="ready",
            recording_policy={"mode": "automatic", "requireSignedURLs": True},
        )

    def rotate_key(self, event: dict) -> ProvisionResult:
        input_id = event["provider_input_id"]
        result = self._request(
            "POST",
            f"/accounts/{self.config.cf_account_id}/stream/live_inputs/{input_id}/rotate_keys",
            {},
        )
        result_body = result.get("result") or result
        rtmps = result_body.get("rtmps") or {}
        return ProvisionResult(
            input_id=input_id,
            ingest_url=rtmps.get("url") or "",
            stream_key=rtmps.get("streamKey") or "",
            state="ready",
            recording_policy={"mode": "automatic", "requireSignedURLs": True},
        )

    def status(self, event: dict) -> ProviderStatus:
        input_id = event.get("provider_input_id")
        if not input_id:
            return ProviderStatus(state="unprovisioned")
        result = self._request(
            "GET",
            f"/accounts/{self.config.cf_account_id}/stream/live_inputs/{input_id}/videos",
        )
        videos = (result.get("result") or result) if isinstance(result, dict) else []
        if isinstance(videos, dict):
            videos = videos.get("videos") or videos.get("result") or []
        live = None
        vod = None
        for item in videos or []:
            state = (item.get("status") or {}).get("state") if isinstance(item.get("status"), dict) else item.get("status")
            uid = item.get("uid") or item.get("id")
            if state in ("live-inprogress", "connected", "live"):
                live = uid
            elif state in ("ready", "readytoplay"):
                vod = uid
        recording = "ready" if vod else ("pending" if event.get("replay_pending") else None)
        return ProviderStatus(
            state=event.get("provider_state") or "unknown",
            active_video_id=live or event.get("provider_video_id"),
            replay_video_id=vod or event.get("provider_replay_video_id"),
            recording_state=recording,
            connected=bool(live),
        )

    def playback_url(self, event: dict, expires_at: float) -> tuple[str, str]:
        video_id = event.get("provider_video_id") or event.get("provider_replay_video_id") or event.get("provider_input_id")
        ttl = max(1, int(expires_at - time.time()))
        result = self._request(
            "POST",
            f"/accounts/{self.config.cf_account_id}/stream/{video_id}/token",
            {"exp": int(expires_at), "downloadable": False, "lifetime": ttl},
        )
        token = (result.get("result") or result).get("token")
        host = f"https://customer-{self.config.cf_customer_code}.cloudflarestream.com"
        return f"{host}/{token}/manifest/video.m3u8", "hls"

    def disable(self, event: dict) -> ProviderStatus:
        input_id = event.get("provider_input_id")
        if input_id:
            self._request(
                "PUT",
                f"/accounts/{self.config.cf_account_id}/stream/live_inputs/{input_id}",
                {"enabled": False},
            )
        st = self.status(event)
        st.state = "disabled"
        return st

    def parse_webhook(self, payload: dict) -> WebhookEvent:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        input_id = (
            data.get("liveInput") or data.get("live_input_id")
            or data.get("uid") or payload.get("uid") or ""
        )
        event_type = payload.get("eventType") or payload.get("type") or ""
        ts = str(payload.get("created") or payload.get("timestamp") or time.time())
        video_id = None
        if isinstance(data.get("video"), dict):
            video_id = data["video"].get("uid")
        video_id = video_id or data.get("videoUID")
        error = None
        status = data.get("status") if isinstance(data.get("status"), dict) else {}
        if status.get("errorReasonCode") or payload.get("error"):
            error = str(status.get("errorReasonText") or payload.get("error"))
        return WebhookEvent(input_id=str(input_id), event_type=str(event_type),
                            timestamp=ts, error=error, video_id=video_id)

    def fetch_analytics(self, event: dict) -> AnalyticsSnapshot:
        video_id = event.get("provider_replay_video_id") or event.get("provider_video_id")
        if not video_id:
            return AnalyticsSnapshot(None, None, None, None, False, {"status": "PROVIDER_DATA_PENDING"})
        try:
            result = self._request(
                "GET",
                f"/accounts/{self.config.cf_account_id}/stream/analytics?metrics=minutesViewed&filters=uid=={video_id}",
            )
        except RuntimeError:
            return AnalyticsSnapshot(video_id, None, None, None, False, {"status": "PROVIDER_DATA_PENDING"})
        minutes = None
        data = result.get("result") or result
        if isinstance(data, dict):
            totals = data.get("totals") or data.get("data") or {}
            if isinstance(totals, dict):
                minutes = totals.get("minutesViewed") or totals.get("minutes_viewed")
        return AnalyticsSnapshot(
            video_id=video_id, minutes_viewed=float(minutes) if minutes is not None else None,
            window_start=None, window_end=None, available=minutes is not None, raw_summary={"provider": "cloudflare"},
        )
