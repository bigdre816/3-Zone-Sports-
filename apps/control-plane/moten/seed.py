"""Seed data: personas, projects, the 6 TZ + 6 TR candidate families, and one
fully reconstructed candidate (TZ-02) that exercises the Phase 1 exit-evidence
path end-to-end (question → observation → invention → contribution → filing →
calendar → disclosure control)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .models import Person, Project
from .planes import decision, invention, signal
from .util import now

PERSONS = [
    ("P-2026-000001", "Andre (Founder)", "founder", True),
    ("P-2026-000002", "IP Steward", "ip_steward", True),
    ("P-2026-000003", "Counsel", "counsel", True),
    ("P-2026-000004", "Research Steward", "research_steward", True),
    ("P-2026-000005", "Technical Lead", "technical_lead", True),
    # A non-natural principal: the approved AI gateway. It can NEVER be an inventor.
    ("P-2026-000099", "approved-ai-gateway", "ai_tool", False),
]

PROJECTS = [
    ("PRJ-2026-000001", "Three-Zone Sports Access"),
    ("PRJ-2026-000002", "Treasure"),
    ("PRJ-2026-000003", "Passport"),
]

# (title, problem, mechanism, project_id) for the candidate families (spec §11-§12).
THREE_ZONE = [
    (
        "TZ-01 Rights-aware distribution router",
        "Events get routed to destinations without verifying rights, territory, window, and device authorization.",
        {
            "inputs": ["household relationship/service-area/package", "event rights", "territory", "window", "device", "approved destination"],
            "transformation": "policy evaluation with rights versioning and entitlement lease; fail-closed on blackout/expiry",
            "outputs": ["included/premium/unavailable state", "route to an authorized experience only"],
        },
    ),
    (
        "TZ-02 Demand-guided rights acquisition engine",
        "Rights are acquired without joining stable longitudinal demand to availability, expiry, production readiness, and economics.",
        {
            "inputs": ["stable question/version observations by geography/relationship/property/time", "conversion/watch/retention facts", "property authority/rights windows/territory/exclusivity/expiry", "feed quality/production mode/cost", "package fit/relevance/risk"],
            "transformation": "normalize without collapsing question versions; relationship-weighted demand score with confidence/freshness; join only verified rights; estimate obligations; apply fail-closed hard constraints; rank",
            "outputs": ["ranked opportunity set with evidence lineage, alternatives, cost range, rights gaps, and a human approval gate"],
        },
    ),
    (
        "TZ-03 Adaptive broadcast orchestration",
        "Production mode is chosen without accounting for rights, demand, feed quality, local capability, cost, and reliability.",
        {
            "inputs": ["rights", "demand", "feed quality", "local capability", "cost", "reliability"],
            "transformation": "production-mode state machine with feed qualification, fallback, rights-bound master, incident authority",
            "outputs": ["selected ingest/certified-producer/full-service mode with readiness and recovery"],
        },
    ),
    (
        "TZ-04 Rights-bound media object",
        "Feeds/archives/derivatives travel without carrying their territory, window, replay, ad, and authorization data.",
        {
            "inputs": ["event_id", "rights_version_id", "permitted destinations/territory/window/uses", "expiration"],
            "transformation": "signed metadata envelope with object version and permitted-use policy; lease evaluation; immutable trace",
            "outputs": ["rights-bound media object with revocation propagation"],
        },
    ),
    (
        "TZ-05 Auditable multi-property settlement",
        "Settlement across many properties cannot be recomputed from immutable inputs and versioned rules.",
        {
            "inputs": ["immutable measurement facts", "governed formula versions", "attribution rules", "correction events"],
            "transformation": "deterministic recomputation with versioned formulas and compensating corrections",
            "outputs": ["auditable settlement with reconciliation and dispute trace"],
        },
    ),
    (
        "TZ-06 Relationship-based sports discovery graph",
        "Discovery cannot navigate family/school/hometown/alumni relations to events under rights and privacy constraints.",
        {
            "inputs": ["relationship edges (family/school/hometown/alumni/conference/affiliate/team-system)", "event", "rights", "entitlement", "availability"],
            "transformation": "graph edge provenance with consent boundaries, rights-aware query, identity minimization, authorized handoff",
            "outputs": ["rights-aware availability navigation with privacy-leakage protection"],
        },
    ),
]

TREASURE = [
    (
        "TR-01 Reward/evidence separation",
        "Rewarding an activity mutates the underlying evidence history.",
        {"inputs": ["bounded activity events", "evidence history"], "transformation": "two-ledger model with signed event references; no reward mutation of source evidence", "outputs": ["independent reward and evidence ledgers with controlled joins"]},
    ),
    (
        "TR-02 Capped score impact with persistent evidence",
        "A single event can distort a score while evidence accumulation is lost.",
        {"inputs": ["events", "score", "evidence graph"], "transformation": "capped contribution function with durable evidence graph and versioned recalculation", "outputs": ["bounded score effect with persistent replayable evidence"]},
    ),
    (
        "TR-03 Multi-activity consistency history",
        "Different evidence types collapse into one unexplainable number.",
        {"inputs": ["activity-specific channels", "time windows"], "transformation": "confidence-weighted, transparent aggregation without collapsing evidence types", "outputs": ["explainable consistency history across activities"]},
    ),
    (
        "TR-04 Participant-selected evidence presentation",
        "Sharing evidence exposes full private history.",
        {"inputs": ["private evidence history", "consented view scope"], "transformation": "selective disclosure with redaction, provenance proof, and revocation", "outputs": ["minimum-disclosure presentation with tamper evidence"]},
    ),
    (
        "TR-05 AI-assisted control architecture",
        "AI assistance blurs human and policy authority.",
        {"inputs": ["human requests", "policy"], "transformation": "tool gateway with action allowlist, human approval, prompt/output hashing", "outputs": ["AI explanation/organization with preserved human authority"]},
    ),
    (
        "TR-06 Anonymous-to-authorized identity transition",
        "Anonymous aggregate intelligence links to identity without an authorized purpose gate.",
        {"inputs": ["pseudonymous IDs", "consent token"], "transformation": "merge ledger with limited/reversible linkage after an authorized purpose gate", "outputs": ["consented, minimized identity linkage with re-identification tests"]},
    ),
]


def already_seeded(session: Session) -> bool:
    return session.query(Person).count() > 0


def seed(session: Session) -> dict:
    if already_seeded(session):
        return {"status": "already-seeded"}

    for pid, name, role, natural in PERSONS:
        session.add(Person(person_id=pid, display_name=name, role_default=role, is_natural_person=natural))
    for prj_id, name in PROJECTS:
        session.add(Project(project_id=prj_id, name=name))
    session.flush()

    tz_ids: list[str] = []
    for title, problem, mechanism in THREE_ZONE:
        inv, _ = invention.create_invention(
            session, title=title, problem=problem, mechanism=mechanism,
            authored_by="P-2026-000001", project_id="PRJ-2026-000001",
            alternatives=[{"variant": "cloud"}, {"variant": "edge"}, {"variant": "human-in-the-loop"}],
            technical_effect="Reduce misdelivery/stale-rights decisions under explicit fail-closed constraints.",
        )
        tz_ids.append(inv.inv_id)
    for title, problem, mechanism in TREASURE:
        invention.create_invention(
            session, title=title, problem=problem, mechanism=mechanism,
            authored_by="P-2026-000001", project_id="PRJ-2026-000002",
            alternatives=[{"variant": "baseline"}, {"variant": "low-resource"}, {"variant": "partner-integrated"}],
            technical_effect="Preserve evidence integrity while bounding reward/score effects.",
        )

    # --- Fully reconstructed candidate: TZ-02 -----------------------------
    tz02 = tz_ids[1]

    rq, _ = signal.create_question(
        session,
        owner_person_id="P-2026-000004",
        exact_wording="Would you pay $5 per month to watch participating sports in your home zone?",
        response_contract={"codes": ["yes", "no", "maybe"], "scale": "categorical"},
        longitudinal_intent="controlled",
        project_id="PRJ-2026-000001",
        first_use_date=date(2026, 9, 2),
    )
    signal.record_observation(
        session, rq_id=rq.rq_id, rq_revision=1,
        payload={"n": 412, "yes_rate": 0.38, "geography": "KC home zone"},
        actor_person_id="P-2026-000004", project_id="PRJ-2026-000001",
    )
    # A changed question is a NEW version, never an in-place edit (spec §04).
    signal.add_question_version(
        session, rq_id=rq.rq_id,
        exact_wording="Would you pay $7 per month for authorized home-zone access including replay?",
        response_contract={"codes": ["yes", "no", "maybe"], "scale": "categorical"},
        change_reason="Changed price ($5→$7) and added replay window.",
        comparability_assessment="Not directly comparable to v1.0: price and access scope differ; treat as related, not one series.",
        actor_person_id="P-2026-000004",
        first_use_date=date(2026, 9, 5),
    )

    invention.add_embodiment(
        session, inv_id=tz02, label="A",
        package={"overview": "Longitudinal demand sensor joined to a rights/production/economics graph emitting a constrained, auditable acquisition queue."},
        authored_by="P-2026-000005",
    )
    invention.set_ip_posture(session, inv_id=tz02, posture="patent", actor_person_id="P-2026-000002")
    invention.add_contribution(
        session, inv_id=tz02, person_id="P-2026-000001",
        contribution_class="mechanism",
        statement="Conceived joining stable longitudinal demand to verified rights authority under fail-closed constraints.",
        attested=True,
    )
    invention.add_contribution(
        session, inv_id=tz02, person_id="P-2026-000005",
        contribution_class="implementation",
        statement="Implemented the constrained ranking with evidence lineage and human approval gate.",
        attested=True,
    )
    invention.record_ai_interaction(
        session, inv_id=tz02, human_operator_person_id="P-2026-000001",
        tool="approved-ai-gateway", purpose="alternative-embodiment-brainstorming",
        human_action="Andre selected the event-scoped rights lease approach and added the fail-closed hard-stop rule.",
        model_identifier="provider-model-vX",
    )
    invention.name_inventors(
        session, inv_id=tz02, inventor_person_ids=["P-2026-000001", "P-2026-000005"],
        actor_person_id="P-2026-000003", approver_person_id="P-2026-000001",
    )

    for target in ["Hypothesis", "Mechanism", "Invention Candidate", "Prior-Art Review", "Provisional Ready"]:
        invention.transition(session, inv_id=tz02, target_state=target, actor_person_id="P-2026-000002")

    # Disclosure that MUST be held: a deck referencing the unfiled TZ-01 mechanism.
    decision.preflight_disclosure(
        session,
        artifact_bytes=b"Partner deck describing the TZ-01 rights-aware routing mechanism and ranking weights.",
        channel="partner-deck", classification="partner-confidential",
        actor_person_id="P-2026-000002",
        linked_unfiled_inventions=[tz_ids[0]],
        purpose="public",
    )
    # A benign public disclosure that is allowed.
    decision.preflight_disclosure(
        session,
        artifact_bytes=b"Public blog post: generic company mission, no mechanisms disclosed.",
        channel="website", classification="public", actor_person_id="P-2026-000002",
    )

    # Record the verified filing for TZ-02 (two-person) → generates the calendar.
    decision.record_filing(
        session, inv_id=tz02, uspto_receipt_ref="USPTO-PROV-63-EXAMPLE",
        verified_filing_date=date(2026, 9, 5),
        named_inventors=["P-2026-000001", "P-2026-000005"],
        supported_versions=[f"{tz02}#v1.0"],
        actor_person_id="P-2026-000002", approver_person_id="P-2026-000003",
        owner="P-2026-000002", backup_owner="P-2026-000001", escalation_owner="P-2026-000003",
    )
    return {"status": "seeded", "reconstructed_candidate": tz02, "rq": rq.rq_id}
