"""Evidence plane: append-only event log, artifacts, hash chain.

Phase 1 records the full event envelope (spec §03) and a linked hash chain.
Cryptographic signatures and WORM object-lock storage are Phase 2/4 hardening.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Artifact, ChainHead, Event
from ..util import (
    allocate_id,
    canonical_payload_hash,
    clock_source,
    now,
    sha256_bytes,
    sha256_text,
)


def _event_hash(event_id: str, payload_sha256: str, previous_hash: str | None) -> str:
    return sha256_text(f"{event_id}|{payload_sha256}|{previous_hash or ''}")


def _moten_head(session: Session) -> ChainHead:
    head = (
        session.query(ChainHead)
        .filter(ChainHead.ledger == "moten")
        .with_for_update()
        .one_or_none()
    )
    if head is None:
        head = ChainHead(ledger="moten", sequence=0, head_hash=None, updated_at=now())
        session.add(head)
        session.flush()
    return head


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
    head = _moten_head(session)
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
        previous_event_hash=head.head_hash,
        legal_effect=legal_effect,
        links=links or [],
    )
    session.add(event)
    session.flush()
    head.sequence = int(head.sequence) + 1
    head.head_hash = _event_hash(event.event_id, event.payload_sha256, event.previous_event_hash)
    head.updated_at = now()
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
    expected_head: str | None = None
    expected_sequence = 0
    for ev in events:
        if ev.previous_event_hash != expected_prev:
            return False
        expected_head = _event_hash(ev.event_id, ev.payload_sha256, ev.previous_event_hash)
        expected_prev = expected_head
        expected_sequence += 1
    head = session.query(ChainHead).filter(ChainHead.ledger == "moten").one_or_none()
    if head is None:
        return expected_sequence == 0
    return int(head.sequence) == expected_sequence and head.head_hash == expected_head
