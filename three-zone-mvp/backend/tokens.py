"""Stateless, HMAC-signed tokens (sessions, playback leases, ingest creds).

The token format is ``<b64url(payload_json)>.<b64url(hmac_sha256)>`` with no
padding. It is deliberately small and dependency-free. Verification is constant
time and always checks the ``typ`` claim and expiry, so a session token can
never be replayed as a lease or ingest credential.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class TokenError(Exception):
    """Raised when a token is malformed, tampered, wrong type, or expired."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hmac_equal(a: str, b: str) -> bool:
    """Constant-time comparison for shared-secret checks (e.g. service keys)."""
    return hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))


def _sign(secret: str, message: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message.encode("ascii"), hashlib.sha256).digest()
    return _b64e(digest)


def sign(secret: str, typ: str, claims: dict, ttl_seconds: int, now: float | None = None) -> str:
    now = time.time() if now is None else now
    payload = dict(claims)
    payload["typ"] = typ
    payload["iat"] = int(now)
    payload["exp"] = int(now) + int(ttl_seconds)
    encoded = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{encoded}.{_sign(secret, encoded)}"


def verify(secret: str, token: str, expected_typ: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if not token or token.count(".") != 1:
        raise TokenError("malformed token")
    encoded, signature = token.split(".", 1)
    expected_sig = _sign(secret, encoded)
    if not hmac.compare_digest(expected_sig, signature):
        raise TokenError("bad signature")
    try:
        payload = json.loads(_b64d(encoded))
    except (ValueError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        raise TokenError("undecodable payload") from exc
    if payload.get("typ") != expected_typ:
        raise TokenError("wrong token type")
    if int(payload.get("exp", 0)) < int(now):
        raise TokenError("expired token")
    return payload
