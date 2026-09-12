"""Three-Zone evidence intake for Moten Phase 1.

The intake surface preserves an immutable copy of each received payload, links it
into the Moten evidence chain, and never blocks Three-Zone runtime operations.

Honesty (Y1c / G0-C): status ``intake_accepted`` means transport receipt into this
control-plane intake store only. It is NOT Treasure Path A review, release, or a
Treasure institution named Moten. See docs/multi-ai/TREASURE-EVIDENCE-VOCABULARY.md.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models import ExternalIntake
from ..util import allocate_id, canonical_payload_hash, now
from . import evidence


def ingest_external_payload(
    session: Session,
    *,
    handoff_type: str,
    payload: dict,
    actor_person_id: str | None = None,
) -> tuple[ExternalIntake, str]:
    source_system = str(payload.get("source_system") or "unknown-source")
    source_object_id = str(
        payload.get("event_id")
        or payload.get("settlement_id")
        or payload.get("object_id")
        or f"{source_system}:{handoff_type}"
    )
    source_version = payload.get("object_version") or payload.get("schema") or "v1"
    rights_version = payload.get("rights_version")
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    artifact = evidence.register_artifact(
        session,
        data=blob,
        mime="application/json",
        data_class="INTERNAL_AUDIT",
        storage_ref=f"{source_system}:{handoff_type}:{source_object_id}",
    )
    intake = ExternalIntake(
        intake_id=allocate_id(session, "EVD"),
        source_system=source_system,
        handoff_type=handoff_type,
        source_object_id=source_object_id,
        source_version=str(source_version),
        rights_version=str(rights_version) if rights_version is not None else None,
        artifact_evd_id=artifact.evd_id,
        payload=payload,
        payload_sha256=canonical_payload_hash(payload),
        recorded_at=now(),
        status="intake_accepted",
    )
    session.add(intake)
    session.flush()
    event = evidence.append_event(
        session,
        event_type=f"three-zone.intake.{handoff_type}.intake_accepted",
        object_id=intake.intake_id,
        object_version=intake.source_version,
        actor_person_id=actor_person_id,
        actor_role="integration",
        payload={
            "source_system": source_system,
            "handoff_type": handoff_type,
            "source_object_id": source_object_id,
            "payload_sha256": intake.payload_sha256,
            "artifact_evd_id": artifact.evd_id,
        },
        links=[source_object_id, artifact.evd_id],
    )
    return intake, event.event_id


def intake_status(session: Session, intake_id: str) -> dict | None:
    record = session.get(ExternalIntake, intake_id)
    if record is None:
        return None
    return {
        "intake_id": record.intake_id,
        "source_system": record.source_system,
        "handoff_type": record.handoff_type,
        "source_object_id": record.source_object_id,
        "source_version": record.source_version,
        "rights_version": record.rights_version,
        "artifact_evd_id": record.artifact_evd_id,
        "payload_sha256": record.payload_sha256,
        "recorded_at": record.recorded_at.isoformat(),
        "status": record.status,
        # Transport receipt only — never Treasure Path A released / R1 / R2.
        "governance": "none",
        "means": "intake_accepted_transport_only",
    }
