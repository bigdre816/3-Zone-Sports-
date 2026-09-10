"""Signal plane: the Longitudinal Research Registry (spec §04).

A question with longitudinal intent cannot be edited in place: a new version
carries a change reason and comparability assessment, and never silently
combines response codes across versions.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..errors import NotFound
from ..models import Observation, ResearchQuestion, ResearchQuestionVersion
from ..util import allocate_id, canonical_payload_hash, now
from . import evidence


def _version_payload(rq_id: str, revision: int, exact_wording: str, response_contract: dict) -> dict:
    return {
        "rq_id": rq_id,
        "revision": revision,
        "exact_wording": exact_wording,
        "response_contract": response_contract,
    }


def create_question(
    session: Session,
    *,
    owner_person_id: str,
    exact_wording: str,
    response_contract: dict,
    longitudinal_intent: str = "exploratory",
    project_id: str | None = None,
    first_use_date: date | None = None,
    sampling: dict | None = None,
    collection: dict | None = None,
    actor_role: str = "research_steward",
) -> tuple[ResearchQuestion, ResearchQuestionVersion]:
    rq_id = allocate_id(session, "RQ")
    rq = ResearchQuestion(
        rq_id=rq_id,
        owner_person_id=owner_person_id,
        project_id=project_id,
        language="en",
        current_revision=1,
        longitudinal_intent=longitudinal_intent,
        created_at=now(),
    )
    session.add(rq)
    version = ResearchQuestionVersion(
        rq_id=rq_id,
        revision=1,
        semver_label="v1.0",
        exact_wording=exact_wording,
        response_contract=response_contract,
        first_use_date=first_use_date,
        valid_from=now(),
        recorded_at=now(),
        sampling=sampling or {},
        collection=collection or {},
        authored_by=owner_person_id,
        payload_sha256=canonical_payload_hash(_version_payload(rq_id, 1, exact_wording, response_contract)),
    )
    session.add(version)
    session.flush()
    evidence.append_event(
        session,
        event_type="research.question.created",
        object_id=rq_id,
        object_version="v1.0",
        actor_person_id=owner_person_id,
        actor_role=actor_role,
        payload=_version_payload(rq_id, 1, exact_wording, response_contract),
        links=[rq_id],
    )
    return rq, version


def add_question_version(
    session: Session,
    *,
    rq_id: str,
    exact_wording: str,
    response_contract: dict,
    change_reason: str,
    comparability_assessment: str,
    actor_person_id: str,
    first_use_date: date | None = None,
    sampling: dict | None = None,
    collection: dict | None = None,
) -> ResearchQuestionVersion:
    rq = session.get(ResearchQuestion, rq_id)
    if rq is None:
        raise NotFound(f"research question {rq_id} not found")
    new_rev = rq.current_revision + 1
    semver = f"v{new_rev}.0"
    version = ResearchQuestionVersion(
        rq_id=rq_id,
        revision=new_rev,
        semver_label=semver,
        exact_wording=exact_wording,
        response_contract=response_contract,
        first_use_date=first_use_date,
        valid_from=now(),
        recorded_at=now(),
        sampling=sampling or {},
        collection=collection or {},
        comparability_assessment=comparability_assessment,
        change_reason=change_reason,
        authored_by=actor_person_id,
        payload_sha256=canonical_payload_hash(_version_payload(rq_id, new_rev, exact_wording, response_contract)),
    )
    session.add(version)
    rq.current_revision = new_rev  # identity pointer only; prior version row preserved
    session.flush()
    evidence.append_event(
        session,
        event_type="research.question.version.committed",
        object_id=rq_id,
        object_version=semver,
        actor_person_id=actor_person_id,
        actor_role="research_steward",
        payload={"change_reason": change_reason, "comparability_assessment": comparability_assessment},
        links=[rq_id],
    )
    return version


def record_observation(
    session: Session,
    *,
    rq_id: str,
    rq_revision: int,
    payload: dict,
    actor_person_id: str,
    project_id: str | None = None,
    source_ref: str | None = None,
    data_class: str = "P1",
    evidence_links: list[str] | None = None,
) -> Observation:
    rq = session.get(ResearchQuestion, rq_id)
    if rq is None:
        raise NotFound(f"research question {rq_id} not found")
    obs = Observation(
        obs_id=allocate_id(session, "OBS"),
        rq_id=rq_id,
        rq_revision=rq_revision,
        project_id=project_id,
        recorded_at=now(),
        source_ref=source_ref,
        data_class=data_class,
        payload=payload,
        evidence_links=evidence_links or [],
    )
    session.add(obs)
    session.flush()
    evidence.append_event(
        session,
        event_type="research.observation.recorded",
        object_id=obs.obs_id,
        actor_person_id=actor_person_id,
        actor_role="research_steward",
        payload={"rq_id": rq_id, "rq_revision": rq_revision, "payload": payload},
        links=[rq_id, obs.obs_id],
    )
    return obs


def question_versions(session: Session, rq_id: str) -> list[ResearchQuestionVersion]:
    return (
        session.query(ResearchQuestionVersion)
        .filter(ResearchQuestionVersion.rq_id == rq_id)
        .order_by(ResearchQuestionVersion.revision.asc())
        .all()
    )
