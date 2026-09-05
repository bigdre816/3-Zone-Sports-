"""Phase 1 data model, grouped by control-plane (AGENTS.md §4).

Version tables carry ``info={"immutable": True}`` so the database layer emits
DELETE/UPDATE guard triggers for them (see database.py). Identity tables hold
the permanent ID and a pointer to the current revision.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

IMMUTABLE = {"immutable": True}


# --------------------------------------------------------------------------
# Directory / shared
# --------------------------------------------------------------------------
class IdSequence(Base):
    __tablename__ = "id_sequence"
    prefix: Mapped[str] = mapped_column(String, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Person(Base):
    __tablename__ = "person"
    person_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    role_default: Mapped[str] = mapped_column(String, nullable=False)
    # AI tools are never natural persons and can never be inventors (spec §06).
    is_natural_person: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")


class Project(Base):
    __tablename__ = "project"
    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)


# --------------------------------------------------------------------------
# Evidence plane
# --------------------------------------------------------------------------
class Artifact(Base):
    __tablename__ = "artifact"
    __table_args__ = {"info": IMMUTABLE}
    evd_id: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    mime: Mapped[str] = mapped_column(String, nullable=False, default="application/octet-stream")
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    data_class: Mapped[str] = mapped_column(String, nullable=False, default="P1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Event(Base):
    """Append-only canonical event log (spec §03 envelope, §16 hash chain)."""

    __tablename__ = "event"
    __table_args__ = {"info": IMMUTABLE}
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[str] = mapped_column(String, nullable=False)
    object_version: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_person_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    clock_source: Mapped[str] = mapped_column(String, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    attestation: Mapped[str | None] = mapped_column(String, nullable=True)
    legal_effect: Mapped[str] = mapped_column(String, nullable=False, default="provenance_only")
    links: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # allowed transition columns (kept for uniformity with version tables)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------
# Signal plane — Research Registry
# --------------------------------------------------------------------------
class ResearchQuestion(Base):
    __tablename__ = "research_question"
    rq_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(ForeignKey("person.person_id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("project.project_id"), nullable=True)
    parent_instrument_id: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    longitudinal_intent: Mapped[str] = mapped_column(String, nullable=False, default="exploratory")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ResearchQuestionVersion(Base):
    __tablename__ = "research_question_version"
    __table_args__ = (
        UniqueConstraint("rq_id", "revision", name="uq_rqv_rev"),
        {"info": IMMUTABLE},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rq_id: Mapped[str] = mapped_column(ForeignKey("research_question.rq_id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    semver_label: Mapped[str] = mapped_column(String, nullable=False)
    exact_wording: Mapped[str] = mapped_column(Text, nullable=False)
    response_contract: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    first_use_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sampling: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    collection: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    comparability_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    authored_by: Mapped[str] = mapped_column(String, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Observation(Base):
    __tablename__ = "observation"
    __table_args__ = {"info": IMMUTABLE}
    obs_id: Mapped[str] = mapped_column(String, primary_key=True)
    rq_id: Mapped[str] = mapped_column(ForeignKey("research_question.rq_id"), nullable=False)
    rq_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("project.project_id"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    data_class: Mapped[str] = mapped_column(String, nullable=False, default="P1")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_links: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------
# Invention plane — Insight-to-Invention Ledger
# --------------------------------------------------------------------------
class Invention(Base):
    __tablename__ = "invention"
    inv_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("project.project_id"), nullable=True)
    root_inv_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifecycle_state: Mapped[str] = mapped_column(String, nullable=False, default="Observation")
    ip_posture: Mapped[str] = mapped_column(String, nullable=False, default="hold")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class InventionVersion(Base):
    __tablename__ = "invention_version"
    __table_args__ = (
        UniqueConstraint("inv_id", "revision", name="uq_invv_rev"),
        {"info": IMMUTABLE},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inv_id: Mapped[str] = mapped_column(ForeignKey("invention.inv_id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    semver_label: Mapped[str] = mapped_column(String, nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    mechanism: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    technical_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    alternatives: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    differentiators: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_behavior: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    security_privacy_boundary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    test_evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    technical_effect: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    authored_by: Mapped[str] = mapped_column(String, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Embodiment(Base):
    __tablename__ = "embodiment"
    __table_args__ = {"info": IMMUTABLE}
    emb_id: Mapped[str] = mapped_column(String, primary_key=True)
    inv_id: Mapped[str] = mapped_column(ForeignKey("invention.inv_id"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    package: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Contribution(Base):
    __tablename__ = "contribution"
    __table_args__ = {"info": IMMUTABLE}
    contribution_id: Mapped[str] = mapped_column(String, primary_key=True)
    inv_id: Mapped[str] = mapped_column(ForeignKey("invention.inv_id"), nullable=False)
    inv_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    person_id: Mapped[str] = mapped_column(ForeignKey("person.person_id"), nullable=False)
    contribution_class: Mapped[str] = mapped_column(String, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    attested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiInteraction(Base):
    __tablename__ = "ai_interaction"
    __table_args__ = {"info": IMMUTABLE}
    ai_record_id: Mapped[str] = mapped_column(String, primary_key=True)
    inv_id: Mapped[str] = mapped_column(ForeignKey("invention.inv_id"), nullable=False)
    human_operator_person_id: Mapped[str] = mapped_column(ForeignKey("person.person_id"), nullable=False)
    tool: Mapped[str] = mapped_column(String, nullable=False)
    model_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    sensitive_data_filter: Mapped[str] = mapped_column(String, nullable=False, default="passed")
    human_action: Mapped[str] = mapped_column(Text, nullable=False)
    human_conception_attestation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Invariant: AI is a tool, never an inventor (spec §06).
    inventor_status_of_ai: Mapped[str] = mapped_column(String, nullable=False, default="tool_only")
    retention: Mapped[str] = mapped_column(String, nullable=False, default="restricted-unfiled-ip")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------
# Decision plane — disclosure firewall, counsel, filing, calendar
# --------------------------------------------------------------------------
class Disclosure(Base):
    __tablename__ = "disclosure"
    disc_id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_sha256: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    audience: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    proposed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    classification: Mapped[str] = mapped_column(String, nullable=False)
    linked_unfiled_inventions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    linked_trade_secrets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    nda: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    risk_color: Mapped[str] = mapped_column(String, nullable=False)
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    approvers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    released_artifact_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    workflow_status: Mapped[str] = mapped_column(String, nullable=False, default="preflighted")


class CounselDecision(Base):
    __tablename__ = "counsel_decision"
    __table_args__ = {"info": IMMUTABLE}
    dec_id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_object_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    decided_by: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_versions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Filing(Base):
    __tablename__ = "filing"
    __table_args__ = {"info": IMMUTABLE}
    app_id: Mapped[str] = mapped_column(String, primary_key=True)
    inv_id: Mapped[str] = mapped_column(ForeignKey("invention.inv_id"), nullable=False)
    uspto_receipt_ref: Mapped[str] = mapped_column(String, nullable=False)
    verified_filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    named_inventors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    supported_versions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    filing_pdf_evd_id: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CalendarEntry(Base):
    __tablename__ = "calendar_entry"
    cal_id: Mapped[str] = mapped_column(String, primary_key=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("filing.app_id"), nullable=False)
    clock_point: Mapped[str] = mapped_column(String, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    counsel_confirmed_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    backup_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    escalation_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    ack_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    ack_record: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_hard_deadline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")


class TradeSecret(Base):
    __tablename__ = "trade_secret"
    ts_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_person_id: Mapped[str] = mapped_column(ForeignKey("person.person_id"), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String, nullable=False, default="high")
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False, default="v1.0")
    handling_label: Mapped[str] = mapped_column(String, nullable=False, default="restricted")
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    access_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SecurityIncident(Base):
    __tablename__ = "security_incident"
    __table_args__ = {"info": IMMUTABLE}
    inc_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    related_object_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
