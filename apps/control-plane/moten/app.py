"""FastAPI application factory: JSON API + reserved later-phase routes.

Dev auth (Phase 1): the acting person is selected via the ``X-Moten-Actor``
header or ``actor`` cookie. Real OIDC + phishing-resistant MFA is a later-phase
target (spec §20). Every date-bearing response carries a legal label.
"""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine

from .config import APP_ROOT
from .database import init_db, make_engine, make_session_factory
from .errors import MotenError
from .models import Person
from .planes import decision, evidence, export, invention, signal
from .schemas import (
    AiInteractionCreate,
    ContributionCreate,
    DisclosurePreflight,
    DisclosureRelease,
    EmbodimentCreate,
    FilingCreate,
    InventionCreate,
    InventorsName,
    IpPostureRequest,
    ObservationCreate,
    QuestionCreate,
    QuestionVersionCreate,
    TransitionRequest,
    VersionCreate,
)

DEFAULT_ACTOR = "P-2026-000001"


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or make_engine()
    init_db(engine)
    SessionFactory = make_session_factory(engine)

    app = FastAPI(title="Moten IP & Invention Control Plane", version="0.1.0-phase1")
    app.state.engine = engine
    app.state.SessionFactory = SessionFactory

    @contextmanager
    def session_scope():
        s = SessionFactory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.state.session_scope = session_scope

    def get_session():
        with session_scope() as s:
            yield s

    def current_actor(
        x_moten_actor: str | None = Header(default=None),
    ) -> str:
        return x_moten_actor or DEFAULT_ACTOR

    @app.exception_handler(MotenError)
    async def _moten_error_handler(_request: Request, exc: MotenError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.__class__.__name__, "detail": str(exc)},
        )

    # ---- Signal plane -----------------------------------------------------
    @app.post("/v1/research/questions", status_code=201)
    def create_question(body: QuestionCreate, s=Depends(get_session)):
        rq, v = signal.create_question(
            s,
            owner_person_id=body.owner_person_id,
            exact_wording=body.exact_wording,
            response_contract=body.response_contract,
            longitudinal_intent=body.longitudinal_intent,
            project_id=body.project_id,
            first_use_date=body.first_use_date,
            sampling=body.sampling,
            collection=body.collection,
        )
        return {"rq_id": rq.rq_id, "revision": v.revision, "semver": v.semver_label}

    @app.post("/v1/research/questions/{rq_id}/versions", status_code=201)
    def add_question_version(rq_id: str, body: QuestionVersionCreate, actor=Depends(current_actor), s=Depends(get_session)):
        v = signal.add_question_version(
            s,
            rq_id=rq_id,
            exact_wording=body.exact_wording,
            response_contract=body.response_contract,
            change_reason=body.change_reason,
            comparability_assessment=body.comparability_assessment,
            actor_person_id=actor,
            first_use_date=body.first_use_date,
            sampling=body.sampling,
            collection=body.collection,
        )
        return {"rq_id": rq_id, "revision": v.revision, "semver": v.semver_label}

    @app.post("/v1/research/observations", status_code=201)
    def record_observation(body: ObservationCreate, actor=Depends(current_actor), s=Depends(get_session)):
        obs = signal.record_observation(
            s,
            rq_id=body.rq_id,
            rq_revision=body.rq_revision,
            payload=body.payload,
            actor_person_id=actor,
            project_id=body.project_id,
            source_ref=body.source_ref,
            data_class=body.data_class,
            evidence_links=body.evidence_links,
        )
        return {"obs_id": obs.obs_id}

    # ---- Invention plane --------------------------------------------------
    @app.post("/v1/inventions", status_code=201)
    def create_invention(body: InventionCreate, actor=Depends(current_actor), s=Depends(get_session)):
        inv, v = invention.create_invention(
            s,
            title=body.title,
            problem=body.problem,
            mechanism=body.mechanism,
            authored_by=actor,
            project_id=body.project_id,
            alternatives=body.alternatives,
            technical_effect=body.technical_effect,
            failure_behavior=body.failure_behavior,
        )
        return {"inv_id": inv.inv_id, "semver": v.semver_label, "lifecycle_state": inv.lifecycle_state}

    @app.post("/v1/inventions/{inv_id}/versions", status_code=201)
    def add_version(inv_id: str, body: VersionCreate, actor=Depends(current_actor), s=Depends(get_session)):
        v = invention.commit_version(
            s,
            inv_id=inv_id,
            problem=body.problem,
            mechanism=body.mechanism,
            authored_by=actor,
            alternatives=body.alternatives,
            technical_effect=body.technical_effect,
            failure_behavior=body.failure_behavior,
            technical_context=body.technical_context,
            security_privacy_boundary=body.security_privacy_boundary,
            test_evidence=body.test_evidence,
            change_reason=body.change_reason,
        )
        return {"inv_id": inv_id, "revision": v.revision, "semver": v.semver_label}

    @app.post("/v1/inventions/{inv_id}/embodiments", status_code=201)
    def add_embodiment(inv_id: str, body: EmbodimentCreate, actor=Depends(current_actor), s=Depends(get_session)):
        emb = invention.add_embodiment(s, inv_id=inv_id, label=body.label, package=body.package, authored_by=actor)
        return {"emb_id": emb.emb_id}

    @app.post("/v1/inventions/{inv_id}/contributions", status_code=201)
    def add_contribution(inv_id: str, body: ContributionCreate, s=Depends(get_session)):
        c = invention.add_contribution(
            s,
            inv_id=inv_id,
            person_id=body.person_id,
            contribution_class=body.contribution_class,
            statement=body.statement,
            attested=body.attested,
            evidence_ref=body.evidence_ref,
        )
        return {"contribution_id": c.contribution_id}

    @app.post("/v1/inventions/{inv_id}/ai-interactions", status_code=201)
    def add_ai_interaction(inv_id: str, body: AiInteractionCreate, s=Depends(get_session)):
        rec = invention.record_ai_interaction(
            s,
            inv_id=inv_id,
            human_operator_person_id=body.human_operator_person_id,
            tool=body.tool,
            purpose=body.purpose,
            human_action=body.human_action,
            model_identifier=body.model_identifier,
            prompt_hash=body.prompt_hash,
            output_hash=body.output_hash,
        )
        return {"ai_record_id": rec.ai_record_id, "inventor_status_of_ai": rec.inventor_status_of_ai}

    @app.post("/v1/inventions/{inv_id}/inventors")
    def name_inventors(inv_id: str, body: InventorsName, actor=Depends(current_actor), s=Depends(get_session)):
        invention.name_inventors(
            s,
            inv_id=inv_id,
            inventor_person_ids=body.inventor_person_ids,
            actor_person_id=actor,
            approver_person_id=body.approver_person_id,
        )
        return {"inv_id": inv_id, "inventors": body.inventor_person_ids}

    @app.post("/v1/inventions/{inv_id}/ip-posture")
    def set_ip_posture(inv_id: str, body: IpPostureRequest, actor=Depends(current_actor), s=Depends(get_session)):
        inv = invention.set_ip_posture(s, inv_id=inv_id, posture=body.posture, actor_person_id=actor)
        return {"inv_id": inv_id, "ip_posture": inv.ip_posture}

    @app.post("/v1/inventions/{inv_id}/transition")
    def transition(inv_id: str, body: TransitionRequest, actor=Depends(current_actor), s=Depends(get_session)):
        inv = invention.transition(
            s,
            inv_id=inv_id,
            target_state=body.target_state,
            actor_person_id=actor,
            approver_person_id=body.approver_person_id,
        )
        return {"inv_id": inv_id, "lifecycle_state": inv.lifecycle_state}

    # ---- Decision plane ---------------------------------------------------
    @app.post("/v1/disclosures/preflight", status_code=201)
    def preflight(body: DisclosurePreflight, actor=Depends(current_actor), s=Depends(get_session)):
        disc = decision.preflight_disclosure(
            s,
            artifact_bytes=body.content.encode("utf-8"),
            channel=body.channel,
            classification=body.classification,
            actor_person_id=actor,
            audience=body.audience,
            linked_unfiled_inventions=body.linked_unfiled_inventions,
            linked_trade_secrets=body.linked_trade_secrets,
            nda=body.nda,
            purpose=body.purpose,
            contains_credentials=body.contains_credentials,
            contains_rights_override=body.contains_rights_override,
            contains_youth_data=body.contains_youth_data,
        )
        return {
            "disc_id": disc.disc_id,
            "decision": disc.decision,
            "risk_color": disc.risk_color,
            "reasons": disc.reasons,
        }

    @app.post("/v1/disclosures/{disc_id}/release")
    def release(disc_id: str, body: DisclosureRelease, actor=Depends(current_actor), s=Depends(get_session)):
        disc = decision.release_disclosure(
            s,
            disc_id=disc_id,
            released_bytes=body.content.encode("utf-8"),
            actor_person_id=actor,
            approver_person_id=body.approver_person_id,
        )
        return {"disc_id": disc.disc_id, "workflow_status": disc.workflow_status, "released_sha256": disc.released_artifact_sha256}

    @app.post("/v1/filings", status_code=201)
    def create_filing(body: FilingCreate, actor=Depends(current_actor), s=Depends(get_session)):
        filing = decision.record_filing(
            s,
            inv_id=body.inv_id,
            uspto_receipt_ref=body.uspto_receipt_ref,
            verified_filing_date=body.verified_filing_date,
            named_inventors=body.named_inventors,
            supported_versions=body.supported_versions,
            actor_person_id=actor,
            approver_person_id=body.approver_person_id,
            owner=body.owner,
            backup_owner=body.backup_owner,
            escalation_owner=body.escalation_owner,
        )
        return {"app_id": filing.app_id, "verified_filing_date": str(filing.verified_filing_date), "date_label": "uspto_filing"}

    @app.get("/v1/calendar")
    def calendar(s=Depends(get_session)):
        from .models import CalendarEntry

        rows = s.query(CalendarEntry).order_by(CalendarEntry.due_date.asc()).all()
        return [
            {
                "cal_id": r.cal_id,
                "app_id": r.app_id,
                "clock_point": r.clock_point,
                "due_date": str(r.due_date),
                "due_date_label": "uspto_filing_derived",
                "is_hard_deadline": r.is_hard_deadline,
                "status": r.status,
            }
            for r in rows
        ]

    # ---- Evidence plane ---------------------------------------------------
    @app.get("/v1/exports/invention/{inv_id}")
    def export_invention(inv_id: str, s=Depends(get_session)):
        return export.build_invention_export(s, inv_id)

    @app.get("/v1/evidence/chain")
    def chain(s=Depends(get_session)):
        return {"verified": evidence.verify_chain(s)}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "version": app.version}

    # ---- Reserved later-phase routes (Phase 3-4): fail closed with 501 ----
    def _reserved():
        return JSONResponse(status_code=501, content={"error": "NotImplemented", "detail": "Reserved for a later phase (spec §13-§17)."})

    for path in [
        "/v1/rights/events/{event_id}/leases",
        "/v1/live/{event_id}/control",
        "/v1/live/{event_id}/revoke",
        "/v1/discovery",
        "/v1/settlements/{period}/close",
    ]:
        app.add_api_route(path, lambda: _reserved(), methods=["POST", "GET"], include_in_schema=True, tags=["reserved"])

    # Mount UI (imported here to avoid a cycle).
    from .web.routes import mount_web

    mount_web(app)
    app.mount("/static", StaticFiles(directory=str(APP_ROOT / "web" / "static")), name="static")
    return app
