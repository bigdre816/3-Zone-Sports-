"""Provider-neutral photo object-storage adapter.

Photos never go to Cloudflare Stream. Clients PUT directly to a one-time
object-store URL when configured (S3/R2). The fake adapter can also accept
bytes through the app's fake-upload route for local/demo use.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from .media_provider import (
    ProviderError, default_http_request, parse_stream_signature,
    stream_webhook_signature,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class PhotoStorage:
    """Direct-to-bucket photo uploads. Parallel to MediaProvider, images only."""

    name = "photo"

    def create_direct_upload(self, kind: str = "photo", **kwargs) -> dict:
        raise NotImplementedError

    def verify_webhook(self, headers: dict, body: dict, raw_body: bytes | None = None) -> bool:
        raise NotImplementedError

    def normalize_webhook(self, headers: dict, raw_body: bytes | None, parsed: dict) -> dict:
        parsed = parsed or {}
        return {
            "provider_event_id": str(parsed.get("provider_event_id") or "").strip(),
            "provider_uid": str(parsed.get("provider_uid") or parsed.get("uid") or "").strip(),
            "status": str(parsed.get("status") or "ready").strip(),
            "duration_seconds": 0,
            "byte_size": parsed.get("byte_size") or parsed.get("size"),
            "job_id": parsed.get("job_id"),
            "error_code": parsed.get("error_code"),
        }

    def playback_metadata(self, provider_uid: str) -> dict:
        return {"provider_uid": provider_uid, "playback_kind": "object_get", "status": "ready"}

    def read_photo(self, provider_uid: str) -> tuple[bytes, str] | None:
        return None

    def playback_url(self, provider_uid: str) -> str | None:
        return None


class FakePhotoStorage(PhotoStorage):
    """In-process / on-disk photo store for demo and tests."""

    name = "fake-photo"

    def __init__(self, webhook_secret: str = "fake-webhook-secret", root=None):
        self.webhook_secret = webhook_secret
        self.root = Path(root) if root else None
        self.uploads: dict = {}
        self.assets: dict = {}
        self.blobs: dict[str, bytes] = {}

    def create_direct_upload(self, kind: str = "photo", **kwargs) -> dict:
        if kind != "photo":
            raise ProviderError("photo storage accepts photos only", "wrong_provider")
        token = _uid("ptok")
        uid = _uid("pho")
        expiry = time.time() + 3600
        self.uploads[token] = {
            "provider_uid": uid, "status": "authorized", "expiry": expiry,
        }
        self.assets[uid] = {
            "status": "authorized", "kind": "photo",
            "byte_size": None, "content_type": "image/jpeg",
        }
        # External PUT target: production clients hit object storage; localFake
        # portal uploads go through /api/network/provider/fake/upload/{token}.
        url = f"https://photos.test/put/{token}"
        return {
            "provider_uid": uid,
            "upload_url": url,
            "upload_token": token,
            "upload_method": "put",
            "expiry": expiry,
            "resumable": False,
        }

    def _persist(self, uid: str, body: bytes, content_type: str) -> None:
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / uid).write_bytes(body)
        else:
            self.blobs[uid] = body
        self.assets[uid] = {
            "status": "ready",
            "kind": "photo",
            "byte_size": len(body),
            "content_type": content_type or "image/jpeg",
        }

    def complete_upload(
        self,
        token: str,
        meta: dict | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> dict:
        session = self.uploads.get(token)
        if not session:
            raise ProviderError("unknown upload token", "unknown_upload")
        if session["expiry"] < time.time():
            raise ProviderError("upload expired", "upload_expired")
        meta = meta or {}
        uid = session["provider_uid"]
        ct = content_type or meta.get("content_type") or "image/jpeg"
        if body is not None:
            self._persist(uid, body, ct)
            size = len(body)
        else:
            size = meta.get("byte_size")
            existing = self.assets.get(uid) or {}
            self.assets[uid] = {
                "status": "ready",
                "kind": "photo",
                "byte_size": size if size is not None else existing.get("byte_size"),
                "content_type": existing.get("content_type") or ct,
            }
        self.uploads[token]["status"] = "uploaded"
        event_id = _uid("pevt")
        return {
            "provider_event_id": event_id,
            "provider_uid": uid,
            "status": "ready",
            "duration_seconds": 0,
            "byte_size": size,
            "signature": self._sign(event_id, uid, "ready"),
        }

    def store_photo(self, token: str, body: bytes, content_type: str = "image/jpeg") -> dict:
        return self.complete_upload(
            token,
            meta={"byte_size": len(body), "content_type": content_type},
            body=body,
            content_type=content_type,
        )

    def read_photo(self, provider_uid: str) -> tuple[bytes, str] | None:
        asset = self.assets.get(provider_uid) or {}
        ct = asset.get("content_type") or "image/jpeg"
        if self.root is not None:
            path = self.root / provider_uid
            if path.is_file():
                return path.read_bytes(), ct
            return None
        blob = self.blobs.get(provider_uid)
        if blob is None:
            return None
        return blob, ct

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


class S3CompatiblePhotoStorage(PhotoStorage):
    """Presigned PUT/GET to an S3-compatible bucket (R2, MinIO, AWS). No Stream."""

    name = "s3"

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str,
                 region: str = "auto", webhook_secret: str = "", http_request=None):
        if not endpoint or not bucket or not access_key or not secret_key:
            raise ProviderError("photo object-store credentials missing", "provider_unconfigured")
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region or "auto"
        self.webhook_secret = webhook_secret
        self.http_request = http_request or default_http_request

    def create_direct_upload(self, kind: str = "photo", **kwargs) -> dict:
        if kind != "photo":
            raise ProviderError("photo storage accepts photos only", "wrong_provider")
        uid = uuid.uuid4().hex
        key = f"photos/{uid}"
        expiry = time.time() + 3600
        url = self._presign_put(key, expires=3600)
        return {
            "provider_uid": uid,
            "upload_url": url,
            "upload_token": uid,
            "upload_method": "put",
            "expiry": expiry,
            "resumable": False,
        }

    def verify_webhook(self, headers: dict, body: dict, raw_body: bytes | None = None) -> bool:
        if not self.webhook_secret:
            return False
        header = ""
        for key, value in (headers or {}).items():
            if key.lower() == "webhook-signature":
                header = value or ""
                break
        if header:
            stamp, sig = parse_stream_signature(header)
            if stamp and sig:
                expected = stream_webhook_signature(self.webhook_secret, raw_body or b"", stamp)
                return hmac.compare_digest(sig, expected)
        secret = ""
        for key, value in (headers or {}).items():
            if key.lower() == "x-network-webhook-secret":
                secret = value or ""
                break
        return bool(secret) and hmac.compare_digest(secret, self.webhook_secret)

    def _presign(self, method: str, key: str, expires: int = 3600) -> str:
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        parsed = urlparse(self.endpoint)
        host = parsed.netloc or parsed.path
        scheme = parsed.scheme or "https"
        credential_scope = f"{datestamp}/{self.region}/s3/aws4_request"
        credential = f"{self.access_key}/{credential_scope}"
        canonical_uri = f"/{self.bucket}/{quote(key, safe='/')}"
        query_items = [
            ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
            ("X-Amz-Credential", credential),
            ("X-Amz-Date", amz_date),
            ("X-Amz-Expires", str(expires)),
            ("X-Amz-SignedHeaders", "host"),
        ]
        canonical_query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
                                   for k, v in query_items)
        canonical_request = (
            f"{method.upper()}\n{canonical_uri}\n{canonical_query}\n"
            f"host:{host}\n\nhost\nUNSIGNED-PAYLOAD"
        )
        string_to_sign = (
            "AWS4-HMAC-SHA256\n"
            f"{amz_date}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )
        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode(), hashlib.sha256).digest()
        k_date = _hmac(("AWS4" + self.secret_key).encode(), datestamp)
        k_region = hmac.new(k_date, self.region.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
        return f"{scheme}://{host}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}"

    def _presign_put(self, key: str, expires: int = 3600) -> str:
        return self._presign("PUT", key, expires=expires)

    def _presign_get(self, key: str, expires: int = 3600) -> str:
        return self._presign("GET", key, expires=expires)

    def playback_url(self, provider_uid: str) -> str:
        return self._presign_get(f"photos/{provider_uid}")

    def read_photo(self, provider_uid: str) -> tuple[bytes, str] | None:
        url = self.playback_url(provider_uid)
        try:
            resp = self.http_request("GET", url)
        except Exception:
            return None
        if getattr(resp, "status", 500) >= 400:
            return None
        body = getattr(resp, "body", None)
        if body is None:
            return None
        ct = "image/jpeg"
        if hasattr(resp, "header"):
            ct = resp.header("Content-Type", "image/jpeg") or "image/jpeg"
        else:
            headers = getattr(resp, "headers", {}) or {}
            for key, value in headers.items():
                if key.lower() == "content-type":
                    ct = value or "image/jpeg"
                    break
        return body, ct.split(";")[0].strip() or "image/jpeg"


def build_photo_storage(config, http_request=None) -> PhotoStorage:
    name = (getattr(config, "photo_storage", "fake") or "fake").strip().lower()
    if name in ("s3", "r2", "minio"):
        return S3CompatiblePhotoStorage(
            getattr(config, "photo_s3_endpoint", ""),
            getattr(config, "photo_s3_bucket", ""),
            getattr(config, "photo_s3_access_key", ""),
            getattr(config, "photo_s3_secret_key", ""),
            getattr(config, "photo_s3_region", "auto") or "auto",
            webhook_secret=getattr(config, "photo_webhook_secret", "") or "",
            http_request=http_request,
        )
    root = getattr(config, "photo_storage_root", None) or None
    return FakePhotoStorage(
        webhook_secret=getattr(config, "fake_webhook_secret", "fake-webhook-secret"),
        root=root,
    )
