"""PBKDF2-HMAC password hashes. Stdlib only; no extra dependency."""

from __future__ import annotations

import hashlib
import hmac
import os
import re

ITERATIONS = 210_000
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
RESERVED = frozenset({
    "demo-owner", "demo-worker", "demo-admin", "owner", "operator", "admin",
    "root", "system",
})


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2$sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not password or not stored:
        return False
    try:
        scheme, algo, iters, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2" or algo != "sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def normalize_username(raw: str) -> str:
    return (raw or "").strip().lower()


def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.match(username))


def valid_password(password: str) -> bool:
    return isinstance(password, str) and 8 <= len(password) <= 128
