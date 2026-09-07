"""UGC media-provider adapter — a replacement seam parallel to demo_media.

Live/replay event files stay on ``demo_media``. Member photos, short clips, and
full games go through this protocol so domain and UI code never import a
specific vendor. The default FakeProvider is used in CI and local demo.
Cloudflare Stream is opt-in through environment variables and is never called
from unittest.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class ProviderError(Exception):
    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


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

    def verify_webhook(self, headers: dict, body: dict) -> bool:
        raise NotImplementedError


@dataclass
class FakeProvider(MediaProvider):
    """In-process provider. Completions are metadata-only — never multi-GB buffers."""

    webhook_secret: str = "fake-webhook-secret"
    name: str = "fake"
    uploads: dict = field(default_factory=dict)
    assets: dict = field(default_factory=dict)
    render_jobs: dict = field(default_factory=dict)

    def create_direct_upload(self, kind: str, **kwargs) -> dict:
        token = _uid("tok")
        uid = _uid("vid")
        expiry = time.time() + 3600
        method = "tus" if kind == "game" else "direct"
        self.uploads[token] = {
            "provider_uid": uid, "kind": kind, "status": "authorized", "expiry": expiry,
        }
        self.assets[uid] = {"status": "authorized", "kind": kind, "duration_seconds": None}
        return {
            "provider_uid": uid,
            "upload_url": f"/api/network/provider/fake/upload/{token}",
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

    def verify_webhook(self, headers: dict, body: dict) -> bool:
        secret = (headers or {}).get("X-Network-Webhook-Secret") or ""
        if secret and hmac.compare_digest(secret, self.webhook_secret):
            return True
        expected = self._sign(
            str(body.get("provider_event_id", "")),
            str(body.get("provider_uid", "")),
            str(body.get("status", "")),
        )
        return hmac.compare_digest(str(body.get("signature", "")), expected)

    def _sign(self, event_id: str, uid: str, status: str) -> str:
        msg = f"{event_id}:{uid}:{status}".encode()
        return hmac.new(self.webhook_secret.encode(), msg, hashlib.sha256).hexdigest()


class CloudflareStreamProvider(MediaProvider):
    """Opt-in Stream adapter. CI never instantiates this with real credentials."""

    name = "cloudflare"

    def __init__(self, account_id: str, api_token: str, webhook_secret: str = ""):
        if not account_id or not api_token:
            raise ProviderError("cloudflare credentials missing", "provider_unconfigured")
        self.account_id = account_id
        self.api_token = api_token
        self.webhook_secret = webhook_secret

    def create_direct_upload(self, kind: str, **kwargs) -> dict:
        raise ProviderError(
            "cloudflare live calls are opt-in via TZ_MEDIA_PROVIDER=cloudflare smoke only",
            "provider_opt_in",
        )

    def get_status(self, provider_uid: str) -> dict:
        raise ProviderError("cloudflare live calls are opt-in", "provider_opt_in")

    def create_clip(self, source_uid: str, start: float, end: float) -> dict:
        raise ProviderError("cloudflare live calls are opt-in", "provider_opt_in")

    def playback_metadata(self, provider_uid: str) -> dict:
        raise ProviderError("cloudflare live calls are opt-in", "provider_opt_in")

    def verify_webhook(self, headers: dict, body: dict) -> bool:
        signature = (headers or {}).get("Webhook-Signature") or ""
        if not self.webhook_secret:
            return False
        payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        expected = hmac.new(self.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)


def build_provider(config) -> MediaProvider:
    name = getattr(config, "media_provider", "fake") or "fake"
    if name == "cloudflare":
        return CloudflareStreamProvider(
            getattr(config, "cloudflare_account_id", ""),
            getattr(config, "cloudflare_api_token", ""),
            getattr(config, "cloudflare_webhook_secret", ""),
        )
    return FakeProvider(webhook_secret=getattr(config, "fake_webhook_secret", "fake-webhook-secret"))
