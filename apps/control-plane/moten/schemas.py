"""Pydantic request models — these double as the OpenAPI contract."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class QuestionCreate(BaseModel):
    owner_person_id: str
    exact_wording: str
    response_contract: dict = Field(default_factory=dict)
    longitudinal_intent: str = "exploratory"
    project_id: str | None = None
    first_use_date: date | None = None
    sampling: dict = Field(default_factory=dict)
    collection: dict = Field(default_factory=dict)


class QuestionVersionCreate(BaseModel):
    exact_wording: str
    response_contract: dict = Field(default_factory=dict)
    change_reason: str
    comparability_assessment: str
    first_use_date: date | None = None
    sampling: dict = Field(default_factory=dict)
    collection: dict = Field(default_factory=dict)


class ObservationCreate(BaseModel):
    rq_id: str
    rq_revision: int
    payload: dict = Field(default_factory=dict)
    project_id: str | None = None
    source_ref: str | None = None
    data_class: str = "P1"
    evidence_links: list[str] = Field(default_factory=list)


class InventionCreate(BaseModel):
    title: str
    problem: str
    mechanism: dict = Field(default_factory=dict)
    project_id: str | None = None
    alternatives: list = Field(default_factory=list)
    technical_effect: str | None = None
    failure_behavior: dict = Field(default_factory=dict)


class VersionCreate(BaseModel):
    problem: str
    mechanism: dict = Field(default_factory=dict)
    alternatives: list = Field(default_factory=list)
    technical_effect: str | None = None
    failure_behavior: dict = Field(default_factory=dict)
    technical_context: dict = Field(default_factory=dict)
    security_privacy_boundary: dict = Field(default_factory=dict)
    test_evidence: dict = Field(default_factory=dict)
    change_reason: str | None = None


class EmbodimentCreate(BaseModel):
    label: str
    package: dict = Field(default_factory=dict)


class ContributionCreate(BaseModel):
    person_id: str
    contribution_class: str
    statement: str
    attested: bool = False
    evidence_ref: str | None = None


class AiInteractionCreate(BaseModel):
    human_operator_person_id: str
    tool: str
    purpose: str
    human_action: str
    model_identifier: str | None = None
    prompt_hash: str | None = None
    output_hash: str | None = None


class InventorsName(BaseModel):
    inventor_person_ids: list[str]
    approver_person_id: str | None = None


class TransitionRequest(BaseModel):
    target_state: str
    approver_person_id: str | None = None


class IpPostureRequest(BaseModel):
    posture: str


class DisclosurePreflight(BaseModel):
    content: str
    channel: str
    classification: str = "public"
    audience: list[str] = Field(default_factory=list)
    linked_unfiled_inventions: list[str] = Field(default_factory=list)
    linked_trade_secrets: list[str] = Field(default_factory=list)
    nda: dict = Field(default_factory=dict)
    purpose: str = "public"
    contains_credentials: bool = False
    contains_rights_override: bool = False
    contains_youth_data: bool = False


class DisclosureRelease(BaseModel):
    content: str
    approver_person_id: str | None = None


class FilingCreate(BaseModel):
    inv_id: str
    uspto_receipt_ref: str
    verified_filing_date: date
    named_inventors: list[str]
    supported_versions: list[str] = Field(default_factory=list)
    approver_person_id: str | None = None
    owner: str
    backup_owner: str | None = None
    escalation_owner: str | None = None
