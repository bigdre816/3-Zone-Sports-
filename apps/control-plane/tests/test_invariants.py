"""Tests for the non-negotiable constitutional invariants (AGENTS.md §2, §6)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from moten.errors import (
    DisclosureBlocked,
    GuardViolation,
    NotNaturalPerson,
    TwoPersonRequired,
)
from moten.models import CalendarEntry, InventionVersion, SecurityIncident
from moten.planes import decision, invention, signal
from moten.util import allocate_id


def _mk_invention(s, **kw):
    return invention.create_invention(
        s,
        title=kw.get("title", "Test"),
        problem=kw.get("problem", "p"),
        mechanism=kw.get("mechanism", {"inputs": ["a"], "transformation": "t", "outputs": ["o"]}),
        authored_by="P-2026-000001",
        alternatives=kw.get("alternatives", [{"v": 1}]),
        technical_effect=kw.get("technical_effect"),
    )


def _persons(s):
    from moten.models import Person

    s.add_all(
        [
            Person(person_id="P-2026-000001", display_name="Andre", role_default="founder", is_natural_person=True),
            Person(person_id="P-2026-000002", display_name="Steward", role_default="ip_steward", is_natural_person=True),
            Person(person_id="P-2026-000099", display_name="ai", role_default="ai_tool", is_natural_person=False),
        ]
    )
    s.flush()


def test_id_format(app):
    with app.state.session_scope() as s:
        rid = allocate_id(s, "INV")
    assert rid.startswith("INV-") and len(rid.split("-")[-1]) == 6


def test_version_row_delete_forbidden(app):
    with app.state.session_scope() as s:
        _persons(s)
        _mk_invention(s)
    with pytest.raises(Exception):
        with app.state.session_scope() as s:
            s.execute(text("DELETE FROM invention_version"))


def test_version_frozen_column_update_forbidden(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        inv_id = inv.inv_id
    with pytest.raises(Exception):
        with app.state.session_scope() as s:
            s.execute(text("UPDATE invention_version SET problem='tampered' WHERE inv_id=:i"), {"i": inv_id})


def test_version_status_transition_allowed(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        inv_id = inv.inv_id
    # Only status/change_reason may change; this must NOT raise.
    with app.state.session_scope() as s:
        s.execute(
            text("UPDATE invention_version SET status='superseded', change_reason='r' WHERE inv_id=:i"),
            {"i": inv_id},
        )
    with app.state.session_scope() as s:
        row = s.query(InventionVersion).filter(InventionVersion.inv_id == inv_id).first()
        assert row.status == "superseded"


def test_correction_preserves_prior_version(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        invention.commit_version(
            s, inv_id=inv.inv_id, problem="p2",
            mechanism={"inputs": ["a"], "transformation": "t2", "outputs": ["o"]},
            authored_by="P-2026-000001", change_reason="refine",
        )
        rows = s.query(InventionVersion).filter(InventionVersion.inv_id == inv.inv_id).all()
        assert {r.revision for r in rows} == {1, 2}


def test_guard_blocks_premature_transition(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s, technical_effect=None)
        with pytest.raises(GuardViolation):
            # No embodiment, no technical effect, posture=hold.
            invention.transition(s, inv_id=inv.inv_id, target_state="Invention Candidate", actor_person_id="P-2026-000002")


def test_ai_cannot_be_contributor(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        with pytest.raises(NotNaturalPerson):
            invention.add_contribution(
                s, inv_id=inv.inv_id, person_id="P-2026-000099",
                contribution_class="mechanism", statement="x",
            )


def test_name_inventors_requires_two_person(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        with pytest.raises(TwoPersonRequired):
            invention.name_inventors(
                s, inv_id=inv.inv_id, inventor_person_ids=["P-2026-000001"],
                actor_person_id="P-2026-000001", approver_person_id="P-2026-000001",
            )


def test_filing_requires_two_person(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        with pytest.raises(TwoPersonRequired):
            decision.record_filing(
                s, inv_id=inv.inv_id, uspto_receipt_ref="R", verified_filing_date=date(2026, 9, 5),
                named_inventors=["P-2026-000001"], supported_versions=[],
                actor_person_id="P-2026-000002", approver_person_id="P-2026-000002", owner="P-2026-000002",
            )


def test_disclosure_holds_when_unfiled_ip_linked(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        disc = decision.preflight_disclosure(
            s, artifact_bytes=b"deck", channel="partner-deck", classification="partner-confidential",
            actor_person_id="P-2026-000002", linked_unfiled_inventions=[inv.inv_id],
        )
        assert disc.risk_color == "red"
        assert disc.decision == "hold-file-first"
        with pytest.raises(DisclosureBlocked):
            decision.release_disclosure(
                s, disc_id=disc.disc_id, released_bytes=b"deck",
                actor_person_id="P-2026-000002", approver_person_id="P-2026-000001",
            )


def test_disclosure_black_creates_incident(app):
    with app.state.session_scope() as s:
        _persons(s)
        disc = decision.preflight_disclosure(
            s, artifact_bytes=b"secret", channel="website", classification="public",
            actor_person_id="P-2026-000002", contains_credentials=True,
        )
        assert disc.risk_color == "black"
        assert s.query(SecurityIncident).count() == 1


def test_disclosure_green_release_requires_two_person(app):
    with app.state.session_scope() as s:
        _persons(s)
        disc = decision.preflight_disclosure(
            s, artifact_bytes=b"benign", channel="website", classification="public",
            actor_person_id="P-2026-000002",
        )
        assert disc.risk_color == "green"
        with pytest.raises(TwoPersonRequired):
            decision.release_disclosure(
                s, disc_id=disc.disc_id, released_bytes=b"benign",
                actor_person_id="P-2026-000002", approver_person_id="P-2026-000002",
            )
        released = decision.release_disclosure(
            s, disc_id=disc.disc_id, released_bytes=b"benign",
            actor_person_id="P-2026-000002", approver_person_id="P-2026-000001",
        )
        assert released.workflow_status == "released"


def test_filing_generates_calendar(app):
    with app.state.session_scope() as s:
        _persons(s)
        inv, _ = _mk_invention(s)
        filing = decision.record_filing(
            s, inv_id=inv.inv_id, uspto_receipt_ref="R", verified_filing_date=date(2026, 9, 5),
            named_inventors=["P-2026-000001"], supported_versions=[],
            actor_person_id="P-2026-000002", approver_person_id="P-2026-000001", owner="P-2026-000002",
        )
        entries = s.query(CalendarEntry).filter(CalendarEntry.app_id == filing.app_id).all()
        assert len(entries) == 5
        assert any(e.is_hard_deadline and e.clock_point == "T12m" for e in entries)
        # 12-month due date is exactly one year later.
        hard = next(e for e in entries if e.clock_point == "T12m")
        assert hard.due_date == date(2027, 9, 5)


def test_question_versioning_is_new_row(app):
    with app.state.session_scope() as s:
        _persons(s)
        rq, _ = signal.create_question(
            s, owner_person_id="P-2026-000001", exact_wording="Pay $5?", response_contract={},
            longitudinal_intent="controlled",
        )
        signal.add_question_version(
            s, rq_id=rq.rq_id, exact_wording="Pay $7?", response_contract={},
            change_reason="price", comparability_assessment="not comparable",
            actor_person_id="P-2026-000001",
        )
        versions = signal.question_versions(s, rq.rq_id)
        assert [v.revision for v in versions] == [1, 2]
        assert versions[0].exact_wording == "Pay $5?"  # prior wording preserved
