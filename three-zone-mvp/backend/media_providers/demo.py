"""Deterministic fake provider for tests and local demo. Never talks to Cloudflare."""

from __future__ import annotations

import time
import uuid

from .base import AnalyticsSnapshot, ProviderStatus, ProvisionResult, WebhookEvent


class DemoProvider:
    name = "demo"

    def __init__(self):
        self.last_create_body: dict | None = None
        self._disabled: set[str] = set()
        self._replay_ready: dict[str, str] = {}
        self.analytics: AnalyticsSnapshot | None = None

    def provision(self, event: dict) -> ProvisionResult:
        event_id = event["event_id"]
        body = live_input_create_body(event, allowed_origins=["http://127.0.0.1:8000"],
                                      delete_after_days=365, prefer_low_latency=False)
        self.last_create_body = body
        key = "demo-stream-key-" + uuid.uuid4().hex
        return ProvisionResult(
            input_id="demo-input-" + event_id,
            ingest_url="rtmps://demo.local/live",
            stream_key=key,
            state="ready",
            recording_policy={"mode": "automatic", "requireSignedURLs": True},
        )

    def rotate_key(self, event: dict) -> ProvisionResult:
        event_id = event["event_id"]
        key = "demo-stream-key-" + uuid.uuid4().hex
        return ProvisionResult(
            input_id=event.get("provider_input_id") or ("demo-input-" + event_id),
            ingest_url="rtmps://demo.local/live",
            stream_key=key,
            state="ready",
            recording_policy={"mode": "automatic", "requireSignedURLs": True},
        )

    def status(self, event: dict) -> ProviderStatus:
        input_id = event.get("provider_input_id") or ""
        if input_id in self._disabled:
            replay = self._replay_ready.get(event["event_id"])
            return ProviderStatus(
                state="disabled",
                replay_video_id=replay,
                recording_state="ready" if replay else "pending",
                connected=False,
            )
        state = event.get("provider_state") or "ready"
        return ProviderStatus(
            state=state,
            active_video_id=event.get("provider_video_id"),
            replay_video_id=event.get("provider_replay_video_id"),
            recording_state="pending" if event.get("replay_pending") else ("ready" if event.get("replay_available") else None),
            connected=state in ("connected", "live", "ready"),
        )

    def playback_url(self, event: dict, expires_at: float) -> tuple[str, str]:
        return f"/demo/media/{event['event_id']}.mp4", "mp4"

    def disable(self, event: dict) -> ProviderStatus:
        input_id = event.get("provider_input_id") or ""
        if input_id:
            self._disabled.add(input_id)
        replay_id = "demo-replay-" + event["event_id"]
        # First disable is pending; mark_replay_ready simulates Cloudflare catching up.
        return ProviderStatus(state="disabled", recording_state="pending", replay_video_id=None, connected=False)

    def mark_replay_ready(self, event_id: str, video_id: str | None = None) -> None:
        self._replay_ready[event_id] = video_id or ("demo-replay-" + event_id)

    def parse_webhook(self, payload: dict) -> WebhookEvent:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        input_id = data.get("liveInput") or data.get("uid") or payload.get("uid") or ""
        event_type = payload.get("eventType") or payload.get("type") or data.get("eventType") or ""
        ts = str(payload.get("timestamp") or data.get("timestamp") or time.time())
        video_id = data.get("videoUID") or data.get("video_id") or payload.get("video_id")
        error = data.get("error") or payload.get("error")
        return WebhookEvent(input_id=str(input_id), event_type=str(event_type),
                            timestamp=ts, error=error, video_id=video_id)

    def fetch_analytics(self, event: dict) -> AnalyticsSnapshot:
        if self.analytics is not None:
            return self.analytics
        return AnalyticsSnapshot(
            video_id=event.get("provider_video_id") or event.get("provider_replay_video_id"),
            minutes_viewed=None, window_start=None, window_end=None,
            available=False, raw_summary={"status": "PROVIDER_DATA_PENDING"},
        )


def live_input_create_body(event: dict, allowed_origins: list[str],
                           delete_after_days: int, prefer_low_latency: bool) -> dict:
    """Canonical create payload. Tests assert recording + signed URLs + origins."""
    origins = [o.replace("https://", "").replace("http://", "").rstrip("/") for o in allowed_origins]
    return {
        "meta": {"name": event.get("title") or event.get("event_id"), "event_id": event.get("event_id")},
        "recording": {
            "mode": "automatic",
            "timeoutSeconds": 30,
            "requireSignedURLs": True,
            "allowedOrigins": origins,
        },
        "deleteRecordingAfterDays": delete_after_days,
        "preferLowLatency": bool(prefer_low_latency),
    }
