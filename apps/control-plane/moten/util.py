"""Shared helpers: trusted clock, content hashing, canonical ID allocation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import CLOCK_SOURCE

# Canonical object prefixes (AGENTS.md §5 / spec §03).
PREFIXES = {
    "RQ",  # research question / instrument
    "OBS",  # observation
    "INV",  # invention candidate / family
    "EMB",  # embodiment
    "EVD",  # evidence artifact / attestation
    "DISC",  # disclosure
    "APP",  # patent application / filing
    "TS",  # trade-secret asset
    "RIGHTS",  # rights grant (reserved, Phase 3)
    "LEASE",  # event lease (reserved, Phase 3)
    "DEC",  # decision
    "CAL",  # deadline / alert
    "P",  # person
    "PRJ",  # project
    "INC",  # security incident
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def clock_source() -> str:
    return CLOCK_SOURCE


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def canonical_payload_hash(payload: dict) -> str:
    """Deterministic hash of a payload dict (sorted keys, compact separators)."""
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def allocate_id(session: Session, prefix: str, when: datetime | None = None) -> str:
    """Allocate a permanent zero-padded ID: PREFIX-YYYY-NNNNNN.

    Uses an upsert-style row lock on directory.id_sequence to guarantee
    monotonic per-(prefix, year) sequences.
    """
    if prefix not in PREFIXES:
        raise ValueError(f"unknown ID prefix: {prefix}")
    year = (when or now()).year
    row = session.execute(
        text("SELECT last_value FROM id_sequence WHERE prefix=:p AND year=:y"),
        {"p": prefix, "y": year},
    ).first()
    if row is None:
        next_value = 1
        session.execute(
            text("INSERT INTO id_sequence (prefix, year, last_value) VALUES (:p, :y, :v)"),
            {"p": prefix, "y": year, "v": next_value},
        )
    else:
        next_value = int(row[0]) + 1
        session.execute(
            text("UPDATE id_sequence SET last_value=:v WHERE prefix=:p AND year=:y"),
            {"v": next_value, "p": prefix, "y": year},
        )
    return f"{prefix}-{year}-{next_value:06d}"
