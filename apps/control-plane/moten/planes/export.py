"""Counsel-ready evidence export package (spec §16).

Assembles the full reconstructable chronology for one invention and a hash
manifest of every included object. This is a provenance package, not a legal
determination.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..errors import NotFound
from ..models import (
    AiInteraction,
    CalendarEntry,
    Contribution,
    Disclosure,
    Embodiment,
    Event,
    Filing,
    Invention,
    InventionVersion,
)
from ..util import canonical_payload_hash, now
from . import evidence


def build_invention_export(session: Session, inv_id: str) -> dict:
    inv = session.get(Invention, inv_id)
    if inv is None:
        raise NotFound(f"invention {inv_id} not found")

    versions = (
        session.query(InventionVersion)
        .filter(InventionVersion.inv_id == inv_id)
        .order_by(InventionVersion.revision.asc())
        .all()
    )
    embodiments = session.query(Embodiment).filter(Embodiment.inv_id == inv_id).all()
    contributions = session.query(Contribution).filter(Contribution.inv_id == inv_id).all()
    ai_records = session.query(AiInteraction).filter(AiInteraction.inv_id == inv_id).all()
    filings = session.query(Filing).filter(Filing.inv_id == inv_id).all()
    filing_ids = [f.app_id for f in filings]
    calendar = (
        session.query(CalendarEntry).filter(CalendarEntry.app_id.in_(filing_ids)).all()
        if filing_ids
        else []
    )
    disclosures = (
        session.query(Disclosure)
        .filter(Disclosure.linked_unfiled_inventions.contains(inv_id))
        .all()
    )
    events = (
        session.query(Event)
        .filter(Event.links.contains(inv_id))
        .order_by(Event.recorded_at.asc())
        .all()
    )

    manifest: list[dict] = []

    def add(kind: str, obj_id: str, payload: dict):
        manifest.append({"kind": kind, "id": obj_id, "sha256": canonical_payload_hash(payload)})

    package = {
        "cover": {
            "invention_id": inv.inv_id,
            "title": inv.title,
            "project_id": inv.project_id,
            "lifecycle_state": inv.lifecycle_state,
            "ip_posture": inv.ip_posture,
            "confidentiality": "restricted-unfiled-ip",
            "generated_at": now().isoformat(),
            "generated_at_label": "internal_provenance",
            "legal_effect": "provenance_only",
            "disclaimer": "Process/evidence record. Counsel determines patentability, inventorship, and filing.",
        },
        "versions": [],
        "embodiments": [],
        "contributions": [],
        "ai_interactions": [],
        "disclosures": [],
        "filings": [],
        "calendar": [],
        "chronology_events": [],
    }

    for v in versions:
        row = {
            "revision": v.revision,
            "semver": v.semver_label,
            "problem": v.problem,
            "mechanism": v.mechanism,
            "alternatives": v.alternatives,
            "technical_effect": v.technical_effect,
            "failure_behavior": v.failure_behavior,
            "status": v.status,
            "payload_sha256": v.payload_sha256,
        }
        package["versions"].append(row)
        add("invention_version", f"{inv_id}#{v.semver_label}", row)

    for e in embodiments:
        row = {"emb_id": e.emb_id, "label": e.label, "package": e.package, "sha256": e.payload_sha256}
        package["embodiments"].append(row)
        add("embodiment", e.emb_id, row)

    for c in contributions:
        row = {
            "contribution_id": c.contribution_id,
            "person_id": c.person_id,
            "class": c.contribution_class,
            "statement": c.statement,
            "attested": c.attested,
        }
        package["contributions"].append(row)
        add("contribution", c.contribution_id, row)

    for a in ai_records:
        row = {
            "ai_record_id": a.ai_record_id,
            "tool": a.tool,
            "purpose": a.purpose,
            "human_action": a.human_action,
            "inventor_status_of_ai": a.inventor_status_of_ai,
        }
        package["ai_interactions"].append(row)
        add("ai_interaction", a.ai_record_id, row)

    for d in disclosures:
        row = {
            "disc_id": d.disc_id,
            "decision": d.decision,
            "risk_color": d.risk_color,
            "reasons": d.reasons,
            "released": d.released_artifact_sha256 is not None,
        }
        package["disclosures"].append(row)
        add("disclosure", d.disc_id, row)

    for f in filings:
        row = {
            "app_id": f.app_id,
            "uspto_receipt_ref": f.uspto_receipt_ref,
            "verified_filing_date": str(f.verified_filing_date),
            "verified_filing_date_label": "uspto_filing",
            "named_inventors": f.named_inventors,
            "supported_versions": f.supported_versions,
        }
        package["filings"].append(row)
        add("filing", f.app_id, row)

    for entry in calendar:
        row = {
            "cal_id": entry.cal_id,
            "clock_point": entry.clock_point,
            "due_date": str(entry.due_date),
            "is_hard_deadline": entry.is_hard_deadline,
            "status": entry.status,
        }
        package["calendar"].append(row)
        add("calendar_entry", entry.cal_id, row)

    for ev in events:
        package["chronology_events"].append(
            {
                "event_id": ev.event_id,
                "event_type": ev.event_type,
                "recorded_at": ev.recorded_at.isoformat(),
                "recorded_at_label": "internal_provenance",
                "payload_sha256": ev.payload_sha256,
                "previous_event_hash": ev.previous_event_hash,
                "legal_effect": ev.legal_effect,
            }
        )

    package["hash_manifest"] = manifest
    package["chain_verified"] = evidence.verify_chain(session)
    package["manifest_sha256"] = canonical_payload_hash({"manifest": manifest})
    return package
