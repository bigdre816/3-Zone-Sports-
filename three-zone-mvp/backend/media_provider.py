"""UGC video-provider adapter — a replacement seam parallel to demo_media.

Live/replay event files stay on ``demo_media``. Member **clips and full games**
go through this protocol. **Photos do not**: they use ``photo_storage``.

The default FakeProvider is used in CI and local demo. Cloudflare Stream is
opt-in through environment variables. Unittests inject a fake HTTP client and
never call the live Stream API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class ProviderError(Exception):
    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


@dataclass
class HttpResponse:
    status: int
    headers: dict
    body: bytes

    def header(self, name: str, default: str = "") -> str:
        want = name.lower()
        for key, value in (self.headers or {}).items():
            if key.lower() == want:
                return value
        return default

    def json(self):
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}


def default_http_request(method: str, url: str, headers: dict | None = None,
                         body: bytes | None = None, timeout: int = 30) -> HttpResponse:
    req = urllib.request.Request(url, data=body, method=method.upper())
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HttpResponse(resp.status, dict(resp.headers.items()), resp.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, dict(exc.headers.items()) if exc.headers else {},
                            exc.read() or b"")


def _b64meta(pairs: dict) -> str:
    parts = []
    for key, value in pairs.items():
        if value is None or value == "":
            continue
        encoded = base64.b64encode(str(value).encode("utf-8")).decode("ascii")
        parts.append(f"{key} {encoded}")
    return ",".join(parts)


def _iso_expiry(seconds: int = 3600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stream_signature(header: str) -> tuple[str, str]:
    """Parse ``Webhook-Signature: time=…,sig1=…`` into (time, sig1)."""
    stamp, sig = "", ""
    for part in (header or "").split(","):
        part = part.strip()
        if part.startswith("time="):
            stamp = part.split("=", 1)[1].strip()
        elif part.startswith("sig1="):
            sig = part.split("=", 1)[1].strip()
    return stamp, sig


def stream_webhook_signature(secret: str, raw_body: bytes, timestamp: str) -> str:
    source = timestamp.encode("utf-8") + b"." + (raw_body or b"")
    return hmac.new(secret.encode("utf-8"), source, hashlib.sha256).hexdigest()


def verify_stream_webhook(secret: str, headers: dict, raw_body: bytes) -> bool:
    if not secret:
        return False
    header = ""
    for key, value in (headers or {}).items():
        if key.lower() == "webhook-signature":
            header = value or ""
            break
    stamp, sig = parse_stream_signature(header)
    if not stamp or not sig:
        return False
    expected = stream_webhook_signature(secret, raw_body or b"", stamp)
    return hmac.compare_digest(sig, expected)


STREAM_STATE_MAP = {
    "ready": "ready",
    "ok": "ready",
    "error": "failed",
    "failed": "failed",
    "queued": "processing",
    "inprogress": "processing",
    "pendingupload": "authorized",
    "downloading": "processing",
    "live-inprogress": "processing",
    "uploaded": "uploaded",
    "processing": "processing",
}


def normalize_stream_webhook(parsed: dict) -> dict:
    parsed = parsed or {}
    uid = str(parsed.get("uid") or parsed.get("provider_uid") or "").strip()
    status_obj = parsed.get("status")
    if isinstance(status_obj, dict):
        state = str(status_obj.get("state") or "").strip().lower()
        error_code = status_obj.get("errorReasonCode") or status_obj.get("error_code")
    else:
        state = str(status_obj or "").strip().lower()
        error_code = parsed.get("error_code")
    if parsed.get("readyToStream") is True and not state:
        state = "ready"
    mapped = STREAM_STATE_MAP.get(state, state or "processing")
    stamp = (
        parsed.get("readyToStreamAt")
        or parsed.get("modified")
        or parsed.get("uploaded")
        or parsed.get("created")
        or ""
    )
    event_id = str(parsed.get("provider_event_id") or "").strip()
    if not event_id and uid:
        event_id = f"{uid}:{mapped}:{stamp}"
    duration = parsed.get("duration")
    if duration is None:
        duration = parsed.get("duration_seconds")
    size = parsed.get("size")
    if size is None:
        size = parsed.get("byte_size")
    return {
        "provider_event_id": event_id,
        "provider_uid": uid,
        "status": mapped,
        "duration_seconds": duration if duration not in (None, -1) else None,
        "byte_size": size,
        "job_id": parsed.get("job_id") or uid,
        "error_code": error_code,
        "clipped_from": parsed.get("clippedFrom") or parsed.get("clipped_from"),
    }


class MediaProvider:
    """Vendor-neutral operations for direct upload, clip render, and webhooks."""

    name = "base"

    def create_direct_upload(self, kind: str, **kwargs) -> dict:
        raise NotImplementedError

    def get_status(self, provider_uid: str) -> dict:
        raise NotImplementedError

    def create_clip(self, source_uid: str, start: float, end: float) -> dict:
        raise NotImplementedError

    def playback_metadata(self, provider_uid: str) -> dict:
        raise NotImplementedError

    def verify_webhook(self, headers: dict, body: dict, raw_body: bytes | None = None) -> bool:
        raise NotImplementedError

    def normalize_webhook(self, headers: dict, raw_body: bytes | None, parsed: dict) -> dict:
        parsed = parsed or {}
        return {
            "provider_event_id": str(parsed.get("provider_event_id") or "").strip(),
            "provider_uid": str(parsed.get("provider_uid") or "").strip(),
            "status": str(parsed.get("status") or "").strip(),
            "duration_seconds": parsed.get("duration_seconds"),
            "byte_size": parsed.get("byte_size"),
            "job_id": parsed.get("job_id"),
            "error_code": parsed.get("error_code"),
        }


@dataclass
class FakeProvider(MediaProvider):
    """In-process video provider. Completions are metadata-only — never multi-GB buffers."""

    webhook_secret: str = "fake-webhook-secret"
    name: str = "fake"
    uploads: dict = field(default_factory=dict)
    assets: dict = field(default_factory=dict)
    render_jobs: dict = field(default_factory=dict)

    def create_direct_upload(self, kind: str, **kwargs) -> dict:
        if kind == "photo":
            raise ProviderError("photos use the photo-storage adapter", "wrong_provider")
        token = _uid("tok")
        uid = _uid("vid")
        expiry = time.time() + 3600
        method = "tus" if kind == "game" else "direct"
        self.uploads[token] = {
            "provider_uid": uid, "kind": kind, "status": "authorized", "expiry": expiry,
        }
        self.assets[uid] = {"status": "authorized", "kind": kind, "duration_seconds": None}
        url = f"/api/network/provider/fake/upload/{token}"
        return {
            "provider_uid": uid,
            "upload_url": url,
            "upload_token": token,
            "upload_method": method,
            "expiry": expiry,
            "resumable": method == "tus",
        }

    def complete_upload(self, token: str, meta: dict | None = None) -> dict:
        session = self.uploads.get(token)
        if not session:
            raise ProviderError("unknown upload token", "unknown_upload")
        if session["expiry"] < time.time():
            raise ProviderError("upload expired", "upload_expired")
        meta = meta or {}
        uid = session["provider_uid"]
        duration = float(meta.get("duration_seconds") or (600 if session["kind"] == "game" else 30))
        self.uploads[token]["status"] = "uploaded"
        self.assets[uid] = {
            "status": "ready",
            "kind": session["kind"],
            "duration_seconds": duration,
            "byte_size": meta.get("byte_size"),
        }
        event_id = _uid("evt")
        return {
            "provider_event_id": event_id,
            "provider_uid": uid,
            "status": "ready",
            "duration_seconds": duration,
            "byte_size": meta.get("byte_size"),
            "signature": self._sign(event_id, uid, "ready"),
        }

    def remember_asset(self, provider_uid: str, kind: str = "clip",
                       duration_seconds=None, status: str = "ready") -> None:
        """Rehydrate in-memory state from the ledger after a process restart."""
        if not provider_uid:
            return
        row = dict(self.assets.get(provider_uid) or {})
        if kind:
            row["kind"] = kind
        if duration_seconds is not None:
            row["duration_seconds"] = duration_seconds
        row["status"] = status or row.get("status") or "ready"
        self.assets[provider_uid] = row

    def get_status(self, provider_uid: str) -> dict:
        asset = self.assets.get(provider_uid)
        if not asset:
            raise ProviderError("unknown asset", "unknown_asset")
        return {"provider_uid": provider_uid, **asset}

    def create_clip(self, source_uid: str, start: float, end: float) -> dict:
        if source_uid not in self.assets:
            raise ProviderError("unknown source", "unknown_asset")
        derived = _uid("clip")
        job_id = _uid("rend")
        duration = max(0.0, float(end) - float(start))
        self.render_jobs[job_id] = {
            "source_uid": source_uid, "derived_uid": derived,
            "start": start, "end": end, "status": "rendering",
        }
        self.assets[derived] = {
            "status": "processing", "kind": "clip", "duration_seconds": duration,
            "source_uid": source_uid,
        }
        return {"provider_uid": derived, "job_id": job_id, "status": "rendering"}

    def finalize_clip(self, job_id: str) -> dict:
        job = self.render_jobs.get(job_id)
        if not job:
            raise ProviderError("unknown render job", "unknown_job")
        job["status"] = "ready"
        derived = job["derived_uid"]
        self.assets[derived]["status"] = "ready"
        event_id = _uid("evt")
        return {
            "provider_event_id": event_id,
            "provider_uid": derived,
            "status": "ready",
            "duration_seconds": self.assets[derived]["duration_seconds"],
            "signature": self._sign(event_id, derived, "ready"),
        }

    def playback_metadata(self, provider_uid: str) -> dict:
        asset = self.get_status(provider_uid)
        return {
            "provider_uid": provider_uid,
            "status": asset["status"],
            "duration_seconds": asset.get("duration_seconds"),
            "playback_kind": "lease_gated_local",
        }

    def verify_webhook(self, headers: dict, body: dict, raw_body: bytes | None = None) -> bool:
        secret = ""
        for key, value in (headers or {}).items():
            if key.lower() == "x-network-webhook-secret":
                secret = value or ""
                break
        if secret and hmac.compare_digest(secret, self.webhook_secret):
            return True
        expected = self._sign(
            str((body or {}).get("provider_event_id", "")),
            str((body or {}).get("provider_uid", "")),
            str((body or {}).get("status", "")),
        )
        return hmac.compare_digest(str((body or {}).get("signature", "")), expected)

    def _sign(self, event_id: str, uid: str, status: str) -> str:
        msg = f"{event_id}:{uid}:{status}".encode()
        return hmac.new(self.webhook_secret.encode(), msg, hashlib.sha256).hexdigest()


class CloudflareStreamProvider(MediaProvider):
    """Cloudflare Stream adapter for **video** (TUS games, basic POST clips).

    Photos are rejected. Tests inject ``http_request``; CI never hits live Stream.
    """

    name = "cloudflare"
    API = "https://api.cloudflare.com/client/v4"

    def __init__(self, account_id: str, api_token: str, webhook_secret: str = "",
                 http_request=None, max_game_bytes: int = 8 * 1024 * 1024 * 1024,
                 max_clip_seconds: int = 90, max_clip_bytes: int = 80 * 1024 * 1024):
        if not account_id or not api_token:
            raise ProviderError("cloudflare credentials missing", "provider_unconfigured")
        self.account_id = account_id
        self.api_token = api_token
        self.webhook_secret = webhook_secret
        self.http_request = http_request or default_http_request
        self.max_game_bytes = int(max_game_bytes)
        self.max_clip_seconds = int(max_clip_seconds)
        self.max_clip_bytes = int(max_clip_bytes)

    def _auth_headers(self, extra: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.api_token}"}
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, path: str, headers: dict | None = None,
                 body: bytes | None = None, query: dict | None = None) -> HttpResponse:
        url = f"{self.API}/accounts/{self.account_id}{path}"
        if query:
            url = url + ("&" if "?" in url else "?") + urlencode(query)
        resp = self.http_request(method, url, headers=headers, body=body)
        if resp.status >= 400:
            detail = ""
            payload = resp.json()
            if isinstance(payload, dict):
                errors = payload.get("errors") or []
                if errors:
                    detail = errors[0].get("message") or ""
            raise ProviderError(
                detail or f"cloudflare HTTP {resp.status}",
                "provider_http_error",
            )
        return resp

    def create_direct_upload(self, kind: str, **kwargs) -> dict:
        if kind == "photo":
            raise ProviderError("photos use the photo-storage adapter", "wrong_provider")
        if kind == "game":
            return self._create_tus_upload(kwargs)
        if kind == "clip":
            return self._create_basic_direct_upload(kwargs)
        raise ProviderError("kind must be clip or full game", "bad_kind")

    def _create_tus_upload(self, kwargs: dict) -> dict:
        length = int(kwargs.get("upload_length") or kwargs.get("max_bytes") or self.max_game_bytes)
        max_bytes = int(kwargs.get("max_bytes") or self.max_game_bytes)
        meta = {"maxsizebytes": str(max_bytes)}
        if kwargs.get("max_duration_seconds"):
            meta["maxdurationseconds"] = str(int(kwargs["max_duration_seconds"]))
        if kwargs.get("creator"):
            meta["name"] = str(kwargs["creator"])
        headers = self._auth_headers({
            "Tus-Resumable": "1.0.0",
            "Upload-Length": str(length),
            "Upload-Metadata": _b64meta(meta),
        })
        resp = self._request("POST", "/stream", headers=headers, query={"direct_user": "true"})
        location = resp.header("Location")
        if not location:
            raise ProviderError("cloudflare TUS create missing Location", "provider_bad_response")
        payload = resp.json() if resp.body else {}
        result = payload.get("result") if isinstance(payload, dict) else None
        uid = ""
        if isinstance(result, dict):
            uid = str(result.get("uid") or "")
        if not uid:
            uid = _uid_from_tus_location(location)
        if not uid:
            raise ProviderError("cloudflare TUS create missing uid", "provider_bad_response")
        expiry = time.time() + 3600
        return {
            "provider_uid": uid,
            "upload_url": location,
            "upload_token": uid,
            "upload_method": "tus",
            "expiry": expiry,
            "resumable": True,
        }

    def _create_basic_direct_upload(self, kwargs: dict) -> dict:
        max_seconds = int(kwargs.get("max_duration_seconds") or self.max_clip_seconds)
        body = json.dumps({
            "maxDurationSeconds": max_seconds,
            "maxSizeBytes": int(kwargs.get("max_bytes") or self.max_clip_bytes),
            "requireSignedURLs": True,
            "expiry": _iso_expiry(3600),
            "meta": {"kind": "clip"},
        }).encode("utf-8")
        resp = self._request(
            "POST", "/stream/direct_upload",
            headers=self._auth_headers({"Content-Type": "application/json"}),
            body=body,
        )
        result = (resp.json() or {}).get("result") or {}
        uid = str(result.get("uid") or "")
        upload_url = result.get("uploadURL") or result.get("uploadUrl") or ""
        if not uid or not upload_url:
            raise ProviderError("cloudflare direct_upload missing uploadURL", "provider_bad_response")
        expiry = time.time() + 3600
        return {
            "provider_uid": uid,
            "upload_url": upload_url,
            "upload_token": uid,
            "upload_method": "direct",
            "expiry": expiry,
            "resumable": False,
        }

    def get_status(self, provider_uid: str) -> dict:
        resp = self._request(
            "GET", f"/stream/{provider_uid}",
            headers=self._auth_headers(),
        )
        result = (resp.json() or {}).get("result") or {}
        state = ((result.get("status") or {}).get("state") or "").lower()
        mapped = STREAM_STATE_MAP.get(state, state or "processing")
        duration = result.get("duration")
        return {
            "provider_uid": provider_uid,
            "status": mapped,
            "duration_seconds": duration if duration not in (None, -1) else None,
            "byte_size": result.get("size"),
            "clipped_from": result.get("clippedFrom"),
            "ready_to_stream": bool(result.get("readyToStream")),
        }

    def create_clip(self, source_uid: str, start: float, end: float) -> dict:
        body = json.dumps({
            "clippedFromVideoUID": source_uid,
            "startTimeSeconds": float(start),
            "endTimeSeconds": float(end),
            "requireSignedURLs": True,
        }).encode("utf-8")
        resp = self._request(
            "POST", "/stream/clip",
            headers=self._auth_headers({"Content-Type": "application/json"}),
            body=body,
        )
        result = (resp.json() or {}).get("result") or {}
        uid = str(result.get("uid") or "")
        if not uid:
            raise ProviderError("cloudflare clip missing uid", "provider_bad_response")
        if uid == source_uid:
            raise ProviderError("clip uid must differ from source", "source_mutated")
        clipped_from = result.get("clippedFrom") or source_uid
        state = ((result.get("status") or {}).get("state") or "").lower()
        ready = bool(result.get("readyToStream")) or state == "ready"
        return {
            "provider_uid": uid,
            "job_id": uid,
            "status": "ready" if ready else "rendering",
            "clipped_from": clipped_from,
        }

    def playback_metadata(self, provider_uid: str) -> dict:
        status = self.get_status(provider_uid)
        return {
            "provider_uid": provider_uid,
            "status": status["status"],
            "duration_seconds": status.get("duration_seconds"),
            "playback_kind": "cloudflare_hls",
        }

    def verify_webhook(self, headers: dict, body: dict, raw_body: bytes | None = None) -> bool:
        return verify_stream_webhook(self.webhook_secret, headers, raw_body or b"")

    def normalize_webhook(self, headers: dict, raw_body: bytes | None, parsed: dict) -> dict:
        return normalize_stream_webhook(parsed)


def _uid_from_tus_location(location: str) -> str:
    path = urlparse(location).path.rstrip("/").split("/")
    for part in reversed(path):
        if part and part not in ("tus", "stream", "upload"):
            return part
    return ""


def build_provider(config, http_request=None) -> MediaProvider:
    name = config.ugc_provider_name() if hasattr(config, "ugc_provider_name") else getattr(config, "media_provider", "fake") or "fake"
    if name == "cloudflare":
        return CloudflareStreamProvider(
            getattr(config, "cloudflare_account_id", "") or getattr(config, "cf_account_id", ""),
            getattr(config, "cloudflare_api_token", "") or getattr(config, "cf_api_token", ""),
            getattr(config, "cloudflare_webhook_secret", "") or getattr(config, "cf_webhook_secret", ""),
            http_request=http_request,
            max_game_bytes=getattr(config, "max_game_bytes", 8 * 1024 * 1024 * 1024),
            max_clip_seconds=getattr(config, "max_post_video_seconds", 90),
        )
    return FakeProvider(webhook_secret=getattr(config, "fake_webhook_secret", "fake-webhook-secret"))
