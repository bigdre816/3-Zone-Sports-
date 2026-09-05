"""Decision plane: disclosure firewall, filing, calendar (spec §08, §10).

Disclosure defaults to hold-file-first when an unfiled patent candidate is
present. The filing calendar is generated from the verified filing date and
cannot be reset by editing a draft.
"""

from __future__ import annotations

import calendar as _cal
from datetime import date

from sqlalchemy.orm import Session

from ..errors import DisclosureBlocked, GuardViolation, NotFound, TwoPersonRequired
from ..models import (
    CalendarEntry,
    Disclosure,
    Event,
    Filing,
    Invention,
    SecurityIncident,
)
from ..util import allocate_id, now, sha256_bytes
from . import evidence

CONTROLLED_PURPOSES = {"legal-review", "diligence", "counsel"}


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last_day = _cal.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def _invention_is_unfiled(session: Session, inv_id: str) -> bool:
    return session.query(Filing).filter(Filing.inv_id == inv_id).count() == 0


def preflight_disclosure(
    session: Session,
    *,
    artifact_bytes: bytes,
    channel: str,
    classification: str,
    actor_person_id: str,
    audience: list | None = None,
    linked_unfiled_inventions: list[str] | None = None,
    linked_trade_secrets: list[str] | None = None,
    nda: dict | None = None,
    purpose: str = "public",
    contains_credentials: bool = False,
    contains_rights_override: bool = False,
    contains_youth_data: bool = False,
) -> Disclosure:
    """Intake → classify → link analysis → risk result (spec §08)."""
    linked_unfiled_inventions = linked_unfiled_inventions or []
    linked_trade_secrets = linked_trade_secrets or []
    nda = nda or {}
    reasons: list[str] = []

    # Link analysis: which linked inventions are actually still unfiled?
    truly_unfiled = [i for i in linked_unfiled_inventions if _invention_is_unfiled(session, i)]

    if contains_credentials or contains_rights_override:
        risk_color, decision = "black", "prohibited"
        reasons.append("prohibited content: credentials or rights-override material")
    elif truly_unfiled or linked_trade_secrets or contains_youth_data:
        # Default: hold and file first unless a controlled legal/diligence purpose.
        if purpose in CONTROLLED_PURPOSES and nda.get("status") == "verified":
            risk_color, decision = "amber", "allowed-under-nda"
            reasons.append("linked unfiled IP/secret released only under verified NDA for controlled purpose")
        else:
            risk_color, decision = "red", "hold-file-first"
            if truly_unfiled:
                reasons.append(f"linked unfiled invention(s): {', '.join(truly_unfiled)}")
            if linked_trade_secrets:
                reasons.append(f"linked trade secret(s): {', '.join(linked_trade_secrets)}")
            if contains_youth_data:
                reasons.append("contains youth/sensitive data")
    elif classification in {"partner-confidential", "nda"} and nda.get("status") != "verified":
        risk_color, decision = "amber", "hold-for-nda"
        reasons.append("confidential classification requires verified NDA before release")
    else:
        risk_color, decision = "green", "allowed"
        reasons.append("no linked unfiled IP, secret, youth data, or contractual restriction")

    disc = Disclosure(
        disc_id=allocate_id(session, "DISC"),
        artifact_sha256=sha256_bytes(artifact_bytes),
        channel=channel,
        audience=audience or [],
        proposed_at=now(),
        classification=classification,
        linked_unfiled_inventions=linked_unfiled_inventions,
        linked_trade_secrets=linked_trade_secrets,
        nda=nda,
        decision=decision,
        risk_color=risk_color,
        reasons=reasons,
        created_by=actor_person_id,
        workflow_status="preflighted",
    )
    session.add(disc)
    session.flush()

    if risk_color == "black":
        incident = SecurityIncident(
            inc_id=allocate_id(session, "INC"),
            kind="prohibited-disclosure-attempt",
            detail=f"Black disclosure attempt on channel '{channel}': {'; '.join(reasons)}",
            related_object_id=disc.disc_id,
            created_at=now(),
            created_by=actor_person_id,
        )
        session.add(incident)
        session.flush()

    evidence.append_event(
        session,
        event_type="disclosure.preflighted",
        object_id=disc.disc_id,
        actor_person_id=actor_person_id,
        actor_role="ip_steward",
        payload={"decision": decision, "risk_color": risk_color, "reasons": reasons},
        legal_effect="disclosure_control",
        links=[disc.disc_id] + linked_unfiled_inventions,
    )
    return disc


def release_disclosure(
    session: Session,
    *,
    disc_id: str,
    released_bytes: bytes,
    actor_person_id: str,
    approver_person_id: str | None,
) -> Disclosure:
    disc = session.get(Disclosure, disc_id)
    if disc is None:
        raise NotFound(f"disclosure {disc_id} not found")
    if disc.risk_color in {"red", "black"}:
        raise DisclosureBlocked(
            f"disclosure {disc_id} is {disc.risk_color} ({disc.decision}); release blocked until resolved by counsel"
        )
    # Green/amber release is a privileged action → two-person control.
    if not approver_person_id or approver_person_id == actor_person_id:
        raise TwoPersonRequired("releasing a disclosure requires a distinct second human approver")
    disc.released_artifact_sha256 = sha256_bytes(released_bytes)
    disc.released_at = now()
    disc.approvers = list({*disc.approvers, actor_person_id, approver_person_id})
    disc.workflow_status = "released"
    session.flush()
    evidence.append_event(
        session,
        event_type="disclosure.released",
        object_id=disc_id,
        actor_person_id=actor_person_id,
        actor_role="ip_steward",
        payload={"released_sha256": disc.released_artifact_sha256, "approved_by": approver_person_id},
        legal_effect="disclosure_control",
        links=[disc_id],
    )
    return disc


CALENDAR_POINTS = [
    ("T6m", 6, False),
    ("T9m", 9, False),
    ("T10m", 10, False),
    ("T11m", 11, False),
    ("T12m", 12, True),
]


def record_filing(
    session: Session,
    *,
    inv_id: str,
    uspto_receipt_ref: str,
    verified_filing_date: date,
    named_inventors: list[str],
    supported_versions: list[str],
    actor_person_id: str,
    approver_person_id: str | None,
    owner: str,
    backup_owner: str | None = None,
    escalation_owner: str | None = None,
    filing_pdf_evd_id: str | None = None,
) -> Filing:
    inv = session.get(Invention, inv_id)
    if inv is None:
        raise NotFound(f"invention {inv_id} not found")
    # Filing is irreversible → two-person control + named inventors required.
    if not approver_person_id or approver_person_id == actor_person_id:
        raise TwoPersonRequired("recording a filing requires a distinct second human approver")
    if not named_inventors:
        raise GuardViolation("a filing requires at least one named inventor")
    if not uspto_receipt_ref:
        raise GuardViolation("Filed status requires a verified USPTO receipt reference")

    filing = Filing(
        app_id=allocate_id(session, "APP"),
        inv_id=inv_id,
        uspto_receipt_ref=uspto_receipt_ref,
        verified_filing_date=verified_filing_date,
        named_inventors=named_inventors,
        supported_versions=supported_versions,
        filing_pdf_evd_id=filing_pdf_evd_id,
        recorded_at=now(),
        created_by=actor_person_id,
    )
    session.add(filing)
    inv.lifecycle_state = "Filed"
    session.flush()

    for point, months, is_hard in CALENDAR_POINTS:
        due = _add_months(verified_filing_date, months)
        session.add(
            CalendarEntry(
                cal_id=allocate_id(session, "CAL"),
                app_id=filing.app_id,
                clock_point=point,
                due_date=due,
                owner=owner,
                backup_owner=backup_owner,
                escalation_owner=escalation_owner,
                ack_deadline=due,
                is_hard_deadline=is_hard,
                status="open",
            )
        )
    session.flush()

    evidence.append_event(
        session,
        event_type="filing.recorded",
        object_id=filing.app_id,
        actor_person_id=actor_person_id,
        actor_role="ip_steward",
        payload={
            "inv_id": inv_id,
            "uspto_receipt_ref": uspto_receipt_ref,
            "verified_filing_date": str(verified_filing_date),
            "named_inventors": named_inventors,
            "approved_by": approver_person_id,
        },
        legal_effect="uspto_filing",
        links=[inv_id, filing.app_id],
    )
    return filing


def acknowledge_calendar_entry(
    session: Session, *, cal_id: str, actor_person_id: str
) -> CalendarEntry:
    entry = session.get(CalendarEntry, cal_id)
    if entry is None:
        raise NotFound(f"calendar entry {cal_id} not found")
    entry.status = "acknowledged"
    entry.ack_record = {"by": actor_person_id, "at": now().isoformat()}
    session.flush()
    return entry


def escalate_overdue(session: Session, *, as_of: date | None = None) -> list[CalendarEntry]:
    """T+11 rule: all unresolved past-due items become escalated (no silent snooze)."""
    as_of = as_of or now().date()
    overdue = (
        session.query(CalendarEntry)
        .filter(CalendarEntry.status == "open", CalendarEntry.due_date <= as_of)
        .all()
    )
    for entry in overdue:
        entry.status = "escalated"
    session.flush()
    return overdue
