"""Evidence plane: append-only event log, artifacts, hash chain.

Phase 1 records the full event envelope (spec §03) and a linked hash chain.
Cryptographic signatures and WORM object-lock storage are Phase 2/4 hardening.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Artifact, Event
from ..util import (
    allocate_id,
    canonical_payload_hash,
    clock_source,
    now,
    sha256_bytes,
    sha256_text,
)


def _chain_hash(prev: Event | None) -> str | None:
    if prev is None:
        return None
    return sha256_text(f"{prev.event_id}|{prev.payload_sha256}|{prev.previous_event_hash or ''}")


def append_event(
    session: Session,
    *,
    event_type: str,
    object_id: str,
    payload: dict,
    object_version: str | None = None,
    actor_person_id: str | None = None,
    actor_role: str | None = None,
    legal_effect: str = "provenance_only",
    links: list[str] | None = None,
) -> Event:
    """Append an immutable, hash-chained event."""
    prev = session.query(Event).order_by(Event.recorded_at.desc(), Event.event_id.desc()).first()
    event = Event(
        event_id=allocate_id(session, "EVD"),
        event_type=event_type,
        object_id=object_id,
        object_version=object_version,
        actor_person_id=actor_person_id,
        actor_role=actor_role,
        recorded_at=now(),
        clock_source=clock_source(),
        payload_sha256=canonical_payload_hash(payload),
        previous_event_hash=_chain_hash(prev),
        legal_effect=legal_effect,
        links=links or [],
    )
    session.add(event)
    session.flush()
    return event


def register_artifact(
    session: Session,
    *,
    data: bytes,
    mime: str = "application/octet-stream",
    data_class: str = "P1",
    storage_ref: str | None = None,
) -> Artifact:
    art = Artifact(
        evd_id=allocate_id(session, "EVD"),
        sha256=sha256_bytes(data),
        mime=mime,
        byte_size=len(data),
        storage_ref=storage_ref,
        data_class=data_class,
        created_at=now(),
    )
    session.add(art)
    session.flush()
    return art


def verify_chain(session: Session) -> bool:
    """Recompute the linked hash chain and confirm continuity."""
    events = session.query(Event).order_by(Event.recorded_at.asc(), Event.event_id.asc()).all()
    expected_prev: str | None = None
    for ev in events:
        if ev.previous_event_hash != expected_prev:
            return False
        expected_prev = sha256_text(f"{ev.event_id}|{ev.payload_sha256}|{ev.previous_event_hash or ''}")
    return True
