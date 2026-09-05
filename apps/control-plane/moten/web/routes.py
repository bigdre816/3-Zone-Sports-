"""Server-rendered counsel/governance workbench (Phase 1 UI surfaces).

Read surfaces plus a live disclosure-preflight form to demonstrate the
firewall. The acting person is selected via the ``actor`` cookie/query.
"""

from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import APP_ROOT
from ..models import (
    CalendarEntry,
    Disclosure,
    Event,
    Filing,
    Invention,
    InventionVersion,
    Person,
    ResearchQuestion,
    SecurityIncident,
)
from ..planes import decision, evidence, export, signal

TEMPLATES = Jinja2Templates(directory=str(APP_ROOT / "web" / "templates"))


def mount_web(app: FastAPI) -> None:
    scope = app.state.session_scope

    def actor_of(request: Request) -> str:
        return request.query_params.get("actor") or request.cookies.get("actor") or "P-2026-000001"

    def base_ctx(request: Request, s):
        persons = s.query(Person).order_by(Person.person_id.asc()).all()
        actor_id = actor_of(request)
        actor = s.get(Person, actor_id)
        return {
            "request": request,
            "persons": persons,
            "actor": actor,
            "actor_id": actor_id,
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        with scope() as s:
            invs = s.query(Invention).order_by(Invention.inv_id.asc()).all()
            rows = []
            for inv in invs:
                latest = (
                    s.query(InventionVersion)
                    .filter(InventionVersion.inv_id == inv.inv_id)
                    .order_by(InventionVersion.revision.desc())
                    .first()
                )
                filing = s.query(Filing).filter(Filing.inv_id == inv.inv_id).first()
                next_deadline = None
                if filing:
                    ce = (
                        s.query(CalendarEntry)
                        .filter(CalendarEntry.app_id == filing.app_id, CalendarEntry.status != "closed")
                        .order_by(CalendarEntry.due_date.asc())
                        .first()
                    )
                    next_deadline = ce.due_date if ce else None
                rows.append(
                    {
                        "inv": inv,
                        "latest": latest,
                        "filed": filing is not None,
                        "filing_date": filing.verified_filing_date if filing else None,
                        "next_deadline": next_deadline,
                    }
                )
            ctx = base_ctx(request, s)
            ctx.update({"rows": rows, "chain_ok": evidence.verify_chain(s)})
            return TEMPLATES.TemplateResponse("dashboard.html", ctx)

    @app.get("/inventions/{inv_id}", response_class=HTMLResponse)
    def invention_detail(inv_id: str, request: Request):
        with scope() as s:
            inv = s.get(Invention, inv_id)
            versions = (
                s.query(InventionVersion)
                .filter(InventionVersion.inv_id == inv_id)
                .order_by(InventionVersion.revision.asc())
                .all()
            )
            pkg = export.build_invention_export(s, inv_id)
            ctx = base_ctx(request, s)
            ctx.update({"inv": inv, "versions": versions, "pkg": pkg})
            return TEMPLATES.TemplateResponse("invention.html", ctx)

    @app.get("/research", response_class=HTMLResponse)
    def research(request: Request):
        with scope() as s:
            questions = s.query(ResearchQuestion).order_by(ResearchQuestion.rq_id.asc()).all()
            data = [{"rq": q, "versions": signal.question_versions(s, q.rq_id)} for q in questions]
            ctx = base_ctx(request, s)
            ctx.update({"questions": data})
            return TEMPLATES.TemplateResponse("research.html", ctx)

    @app.get("/disclosures", response_class=HTMLResponse)
    def disclosures(request: Request):
        with scope() as s:
            discs = s.query(Disclosure).order_by(Disclosure.disc_id.asc()).all()
            incidents = s.query(SecurityIncident).order_by(SecurityIncident.inc_id.asc()).all()
            invs = s.query(Invention).order_by(Invention.inv_id.asc()).all()
            ctx = base_ctx(request, s)
            ctx.update({"discs": discs, "incidents": incidents, "inventions": invs})
            return TEMPLATES.TemplateResponse("disclosures.html", ctx)

    @app.post("/disclosures/preflight")
    def do_preflight(
        request: Request,
        content: str = Form(...),
        channel: str = Form(...),
        classification: str = Form("public"),
        linked_unfiled_inventions: str = Form(""),
        contains_credentials: str = Form(""),
        contains_youth_data: str = Form(""),
    ):
        actor_id = actor_of(request)
        linked = [x.strip() for x in linked_unfiled_inventions.split(",") if x.strip()]
        with scope() as s:
            decision.preflight_disclosure(
                s,
                artifact_bytes=content.encode("utf-8"),
                channel=channel,
                classification=classification,
                actor_person_id=actor_id,
                linked_unfiled_inventions=linked,
                contains_credentials=bool(contains_credentials),
                contains_youth_data=bool(contains_youth_data),
            )
        return RedirectResponse(url=f"/disclosures?actor={actor_id}", status_code=303)

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar_view(request: Request):
        with scope() as s:
            entries = s.query(CalendarEntry).order_by(CalendarEntry.due_date.asc()).all()
            rows = []
            for e in entries:
                filing = s.get(Filing, e.app_id)
                rows.append({"e": e, "inv_id": filing.inv_id if filing else None})
            ctx = base_ctx(request, s)
            ctx.update({"rows": rows})
            return TEMPLATES.TemplateResponse("calendar.html", ctx)

    @app.get("/events", response_class=HTMLResponse)
    def events_view(request: Request):
        with scope() as s:
            evs = s.query(Event).order_by(Event.recorded_at.asc(), Event.event_id.asc()).all()
            ctx = base_ctx(request, s)
            ctx.update({"events": evs, "chain_ok": evidence.verify_chain(s)})
            return TEMPLATES.TemplateResponse("events.html", ctx)
