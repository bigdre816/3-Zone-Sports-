"""Invention plane: Insight-to-Invention Ledger (spec §05, §06).

Enforces the mechanism-first rule, the candidate lifecycle with fail-closed
guards, human-conception ownership (AI is tool-only, never an inventor), and
two-person control on irreversible actions (AGENTS.md §6).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..errors import GuardViolation, NotFound, NotNaturalPerson, TwoPersonRequired
from ..models import (
    AiInteraction,
    Contribution,
    Embodiment,
    Event,
    Invention,
    InventionVersion,
    Person,
)
from ..util import allocate_id, canonical_payload_hash, now
from . import evidence

LIFECYCLE = [
    "Observation",
    "Hypothesis",
    "Mechanism",
    "Invention Candidate",
    "Prior-Art Review",
    "Provisional Ready",
    "Filed",
    "12-Month Decision",
    "Continuation Family",
    "Granted",
    "Abandoned",
    "Trade Secret",
]

# Targets that require a distinct second human approver.
TWO_PERSON_TARGETS = {"Trade Secret", "Granted", "Abandoned"}
# "Filed" is reachable only through a verified filing (decision plane), not here.
FILING_ONLY_TARGETS = {"Filed"}

CONTRIBUTION_CLASSES = {
    "problem",
    "constraint",
    "mechanism",
    "selection",
    "implementation",
    "verification",
}


def _latest_version(session: Session, inv_id: str) -> InventionVersion:
    v = (
        session.query(InventionVersion)
        .filter(InventionVersion.inv_id == inv_id)
        .order_by(InventionVersion.revision.desc())
        .first()
    )
    if v is None:
        raise NotFound(f"no version for invention {inv_id}")
    return v


def _version_payload(inv_id: str, revision: int, problem: str, mechanism: dict) -> dict:
    return {"inv_id": inv_id, "revision": revision, "problem": problem, "mechanism": mechanism}


def create_invention(
    session: Session,
    *,
    title: str,
    problem: str,
    mechanism: dict,
    authored_by: str,
    project_id: str | None = None,
    alternatives: list | None = None,
    technical_effect: str | None = None,
    failure_behavior: dict | None = None,
) -> tuple[Invention, InventionVersion]:
    inv_id = allocate_id(session, "INV")
    inv = Invention(
        inv_id=inv_id,
        project_id=project_id,
        root_inv_id=inv_id,
        title=title,
        current_revision=1,
        lifecycle_state="Observation",
        ip_posture="hold",
        created_at=now(),
    )
    session.add(inv)
    version = InventionVersion(
        inv_id=inv_id,
        revision=1,
        semver_label="v1.0",
        problem=problem,
        mechanism=mechanism,
        alternatives=alternatives or [],
        technical_effect=technical_effect,
        failure_behavior=failure_behavior or {},
        recorded_at=now(),
        valid_from=now(),
        authored_by=authored_by,
        payload_sha256=canonical_payload_hash(_version_payload(inv_id, 1, problem, mechanism)),
    )
    session.add(version)
    session.flush()
    evidence.append_event(
        session,
        event_type="invention.created",
        object_id=inv_id,
        object_version="v1.0",
        actor_person_id=authored_by,
        actor_role="inventor",
        payload=_version_payload(inv_id, 1, problem, mechanism),
        links=[inv_id],
    )
    return inv, version


def commit_version(
    session: Session,
    *,
    inv_id: str,
    problem: str,
    mechanism: dict,
    authored_by: str,
    alternatives: list | None = None,
    technical_effect: str | None = None,
    failure_behavior: dict | None = None,
    technical_context: dict | None = None,
    security_privacy_boundary: dict | None = None,
    test_evidence: dict | None = None,
    change_reason: str | None = None,
) -> InventionVersion:
    inv = session.get(Invention, inv_id)
    if inv is None:
        raise NotFound(f"invention {inv_id} not found")
    new_rev = inv.current_revision + 1
    version = InventionVersion(
        inv_id=inv_id,
        revision=new_rev,
        semver_label=f"v{new_rev}.0",
        problem=problem,
        mechanism=mechanism,
        alternatives=alternatives or [],
        technical_effect=technical_effect,
        technical_context=technical_context or {},
        failure_behavior=failure_behavior or {},
        security_privacy_boundary=security_privacy_boundary or {},
        test_evidence=test_evidence or {},
        recorded_at=now(),
        valid_from=now(),
        authored_by=authored_by,
        change_reason=change_reason,
        payload_sha256=canonical_payload_hash(_version_payload(inv_id, new_rev, problem, mechanism)),
    )
    session.add(version)
    inv.current_revision = new_rev
    session.flush()
    evidence.append_event(
        session,
        event_type="invention.version.committed",
        object_id=inv_id,
        object_version=version.semver_label,
        actor_person_id=authored_by,
        actor_role="inventor",
        payload={"revision": new_rev, "change_reason": change_reason},
        links=[inv_id],
    )
    return version


def add_embodiment(
    session: Session, *, inv_id: str, label: str, package: dict, authored_by: str
) -> Embodiment:
    if session.get(Invention, inv_id) is None:
        raise NotFound(f"invention {inv_id} not found")
    emb = Embodiment(
        emb_id=f"{inv_id.replace('INV', 'EMB')}-{label}",
        inv_id=inv_id,
        label=label,
        package=package,
        recorded_at=now(),
        payload_sha256=canonical_payload_hash({"inv_id": inv_id, "label": label, "package": package}),
    )
    session.add(emb)
    session.flush()
    evidence.append_event(
        session,
        event_type="invention.embodiment.added",
        object_id=emb.emb_id,
        actor_person_id=authored_by,
        actor_role="technical_lead",
        payload={"inv_id": inv_id, "label": label},
        links=[inv_id, emb.emb_id],
    )
    return emb


def add_contribution(
    session: Session,
    *,
    inv_id: str,
    person_id: str,
    contribution_class: str,
    statement: str,
    attested: bool = False,
    evidence_ref: str | None = None,
) -> Contribution:
    inv = session.get(Invention, inv_id)
    if inv is None:
        raise NotFound(f"invention {inv_id} not found")
    if contribution_class not in CONTRIBUTION_CLASSES:
        raise GuardViolation(f"unknown contribution class: {contribution_class}")
    person = session.get(Person, person_id)
    if person is None:
        raise NotFound(f"person {person_id} not found")
    # Invariant: only natural persons may contribute to conception (spec §06).
    if not person.is_natural_person:
        raise NotNaturalPerson("AI/tools cannot be recorded as contributors; use an AI-interaction record")
    contribution = Contribution(
        contribution_id=allocate_id(session, "EVD"),
        inv_id=inv_id,
        inv_revision=inv.current_revision,
        person_id=person_id,
        contribution_class=contribution_class,
        statement=statement,
        evidence_ref=evidence_ref,
        attested=attested,
        attested_at=now() if attested else None,
        recorded_at=now(),
    )
    session.add(contribution)
    session.flush()
    evidence.append_event(
        session,
        event_type="invention.contribution.recorded",
        object_id=contribution.contribution_id,
        actor_person_id=person_id,
        actor_role="inventor",
        payload={"inv_id": inv_id, "class": contribution_class, "attested": attested},
        links=[inv_id, contribution.contribution_id],
    )
    return contribution


def record_ai_interaction(
    session: Session,
    *,
    inv_id: str,
    human_operator_person_id: str,
    tool: str,
    purpose: str,
    human_action: str,
    model_identifier: str | None = None,
    prompt_hash: str | None = None,
    output_hash: str | None = None,
) -> AiInteraction:
    if session.get(Invention, inv_id) is None:
        raise NotFound(f"invention {inv_id} not found")
    rec = AiInteraction(
        ai_record_id=allocate_id(session, "EVD"),
        inv_id=inv_id,
        human_operator_person_id=human_operator_person_id,
        tool=tool,
        model_identifier=model_identifier,
        purpose=purpose,
        prompt_hash=prompt_hash,
        output_hash=output_hash,
        human_action=human_action,
        human_conception_attestation=True,
        inventor_status_of_ai="tool_only",  # invariant, not user-settable
        recorded_at=now(),
    )
    session.add(rec)
    session.flush()
    evidence.append_event(
        session,
        event_type="invention.ai_interaction.recorded",
        object_id=rec.ai_record_id,
        actor_person_id=human_operator_person_id,
        actor_role="ip_steward",
        payload={"inv_id": inv_id, "tool": tool, "inventor_status_of_ai": "tool_only"},
        links=[inv_id, rec.ai_record_id],
    )
    return rec


def name_inventors(
    session: Session,
    *,
    inv_id: str,
    inventor_person_ids: list[str],
    actor_person_id: str,
    approver_person_id: str | None,
) -> None:
    inv = session.get(Invention, inv_id)
    if inv is None:
        raise NotFound(f"invention {inv_id} not found")
    # Two-person control (AGENTS.md §6).
    if not approver_person_id or approver_person_id == actor_person_id:
        raise TwoPersonRequired("naming inventors requires a distinct second human approver")
    for pid in inventor_person_ids:
        person = session.get(Person, pid)
        if person is None:
            raise NotFound(f"person {pid} not found")
        if not person.is_natural_person:
            raise NotNaturalPerson(f"{pid} is not a natural person and cannot be an inventor")
    evidence.append_event(
        session,
        event_type="invention.inventors.named",
        object_id=inv_id,
        actor_person_id=actor_person_id,
        actor_role="counsel",
        payload={"inventors": inventor_person_ids, "approved_by": approver_person_id},
        links=[inv_id],
    )


def _inventors_named(session: Session, inv_id: str) -> bool:
    return (
        session.query(Event)
        .filter(Event.event_type == "invention.inventors.named", Event.object_id == inv_id)
        .count()
        > 0
    )


def _has_embodiment(session: Session, inv_id: str) -> bool:
    return session.query(Embodiment).filter(Embodiment.inv_id == inv_id).count() > 0


def _has_attested_contribution(session: Session, inv_id: str) -> bool:
    return (
        session.query(Contribution)
        .filter(Contribution.inv_id == inv_id, Contribution.attested.is_(True))
        .count()
        > 0
    )


def _check_guard(session: Session, inv: Invention, target: str) -> None:
    """Fail-closed guards for lifecycle advancement (spec §05)."""
    latest = _latest_version(session, inv.inv_id)
    if target == "Mechanism":
        mech = latest.mechanism or {}
        if not all(mech.get(k) for k in ("inputs", "transformation", "outputs")):
            raise GuardViolation("Mechanism requires inputs, transformation, and outputs")
    if target == "Invention Candidate":
        if not _has_embodiment(session, inv.inv_id):
            raise GuardViolation("Invention Candidate requires at least one embodiment")
        if not latest.technical_effect:
            raise GuardViolation("Invention Candidate requires a stated technical effect")
        if inv.ip_posture == "hold":
            raise GuardViolation("Invention Candidate requires an assigned IP posture")
    if target == "Provisional Ready":
        if not latest.alternatives:
            raise GuardViolation("Provisional Ready requires at least one alternative embodiment")
        if not _has_attested_contribution(session, inv.inv_id):
            raise GuardViolation("Provisional Ready requires at least one attested human contribution")
        if not _inventors_named(session, inv.inv_id):
            raise GuardViolation("Provisional Ready requires named inventors")


def transition(
    session: Session,
    *,
    inv_id: str,
    target_state: str,
    actor_person_id: str,
    approver_person_id: str | None = None,
) -> Invention:
    inv = session.get(Invention, inv_id)
    if inv is None:
        raise NotFound(f"invention {inv_id} not found")
    if target_state not in LIFECYCLE:
        raise GuardViolation(f"unknown lifecycle state: {target_state}")
    if target_state in FILING_ONLY_TARGETS:
        raise GuardViolation("'Filed' is reachable only by recording a verified USPTO filing")
    if target_state in TWO_PERSON_TARGETS and (not approver_person_id or approver_person_id == actor_person_id):
        raise TwoPersonRequired(f"transition to '{target_state}' requires a distinct second human approver")
    _check_guard(session, inv, target_state)
    prior = inv.lifecycle_state
    inv.lifecycle_state = target_state
    session.flush()
    evidence.append_event(
        session,
        event_type="invention.lifecycle.transitioned",
        object_id=inv_id,
        actor_person_id=actor_person_id,
        actor_role="ip_steward",
        payload={"from": prior, "to": target_state, "approved_by": approver_person_id},
        links=[inv_id],
    )
    return inv


def set_ip_posture(session: Session, *, inv_id: str, posture: str, actor_person_id: str) -> Invention:
    inv = session.get(Invention, inv_id)
    if inv is None:
        raise NotFound(f"invention {inv_id} not found")
    if posture not in {"patent", "trade_secret", "hybrid", "copyright", "hold"}:
        raise GuardViolation(f"unknown IP posture: {posture}")
    inv.ip_posture = posture
    session.flush()
    evidence.append_event(
        session,
        event_type="invention.ip_posture.set",
        object_id=inv_id,
        actor_person_id=actor_person_id,
        actor_role="ip_steward",
        payload={"posture": posture},
        links=[inv_id],
    )
    return inv
