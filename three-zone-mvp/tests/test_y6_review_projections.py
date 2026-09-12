"""Y6 — Treasure review/revision status as read-only projections.

Seats stay in Treasure. Append-only revisions. intake_accepted ≠ released.
Released projection must not set local treasure_release authority true.
"""

from __future__ import annotations

import ast
import re
import sys
import time
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.config import reset_settings
from threezone_ai.proposals import (
    CANONICAL_STATUSES,
    PROJECTION_SCHEMA_REF,
    STATUS_INTAKE_ACCEPTED,
    AiProposalStore,
    InvalidTreasureReceipt,
    ProjectionImmutable,
    TreasureDeliveryOutbox,
    TreasureDeliveryService,
    TreasureProjectionService,
    TreasureRevisionProjectionStore,
    content_hash_for_segments,
    reset_delivery_service,
    reset_projection_service,
    reset_propose_service,
    validate_treasure_receipt,
)
from threezone_ai.proposals.types import PROPOSAL_SCHEMA_REF, TranscriptionProposal


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    monkeypatch.delenv("TZ_MOTEN_SERVICE_URL", raising=False)
    reset_settings()
    reset_propose_service()
    reset_delivery_service()
    reset_projection_service()
    yield
    reset_settings()
    reset_propose_service()
    reset_delivery_service()
    reset_projection_service()


def _sample_proposal(**overrides) -> TranscriptionProposal:
    segs = [
        {"start": 0.0, "end": 1.0, "text": "y6 projection", "speaker": "a"},
    ]
    base = dict(
        proposal_id="aip_y6test00000001",
        job_id="aij_y6job00000001",
        source_asset_id="asset:synthetic:y6-001",
        segments=segs,
        content_hash=content_hash_for_segments(segs),
        created_at=time.time(),
        status="proposed",
        schema_ref=PROPOSAL_SCHEMA_REF,
        publish=False,
        treasure_release=False,
        human_review_required=True,
        provider="transcription_local",
        lineage_id="lin_y6lineage0001",
    )
    base.update(overrides)
    return TranscriptionProposal(**base)


def _receipt(status: str, **extra) -> dict:
    body = {
        "canonical_packet_id": "pkt_treasure_y6_001",
        "canonical_revision_id": "rev_treasure_y6_001",
        "canonical_status": status,
    }
    body.update(extra)
    return body


def _svc_with_proposal(prop: TranscriptionProposal | None = None):
    prop = prop or _sample_proposal()
    store = AiProposalStore(":memory:")
    store.insert(prop)
    outbox = TreasureDeliveryOutbox(":memory:")
    proj_store = TreasureRevisionProjectionStore(":memory:")
    proj = TreasureProjectionService(
        proj_store, propose_get=store.get, delivery_outbox=outbox
    )
    delivery = TreasureDeliveryService(
        outbox,
        propose_get=store.get,
        moten_service_url="",
        projection_service=proj,
    )
    return prop, store, outbox, proj, delivery


# ---------------------------------------------------------------------------
# Apply admitted / in_review / released → projections update
# ---------------------------------------------------------------------------


def test_apply_admitted_in_review_released_updates_projections():
    prop, store, outbox, proj, delivery = _svc_with_proposal()

    # Seed a delivery row so canonical_* mirror has a target
    from threezone_ai.proposals.delivery import DeliveryReceipt, HANDOFF_TYPE

    ts = time.time()
    outbox.insert(
        DeliveryReceipt(
            delivery_id="tdl_y6seed00000001",
            proposal_id=prop.proposal_id,
            job_id=prop.job_id,
            content_hash=prop.content_hash,
            handoff_type=HANDOFF_TYPE,
            payload={"treasure_release": False, "publish": False},
            status=STATUS_INTAKE_ACCEPTED,
            created_at=ts,
            updated_at=ts,
            delivered_at=ts,
        )
    )

    r1 = proj.apply_treasure_receipt(prop.proposal_id, _receipt("admitted"))
    assert r1.canonical_status == "admitted"
    assert r1.to_dict()["treasure_release"] is False
    assert r1.to_dict()["projection_only"] is True
    assert outbox.latest_for_proposal(prop.proposal_id).canonical_status == "admitted"

    r2 = proj.apply_treasure_receipt(
        prop.proposal_id,
        _receipt("in_review", canonical_revision_id="rev_treasure_y6_002"),
    )
    assert r2.canonical_status == "in_review"
    assert proj.latest(prop.proposal_id).canonical_status == "in_review"
    assert len(proj.list_revisions(prop.proposal_id)) == 2

    r3 = proj.apply_treasure_receipt(
        prop.proposal_id,
        _receipt("released", canonical_revision_id="rev_treasure_y6_003"),
    )
    assert r3.canonical_status == "released"
    latest_delivery = outbox.latest_for_proposal(prop.proposal_id)
    assert latest_delivery.canonical_status == "released"
    assert latest_delivery.payload.get("treasure_release") is False
    d = r3.to_dict()
    assert d["treasure_release"] is False
    assert d["local_release_authority"] is False
    assert d["projection_only"] is True


def test_vocabulary_contains_required_statuses():
    required = {
        "admitted",
        "in_review",
        "changes_requested",
        "released",
        "rejected",
        "corrected",
        "superseded",
    }
    assert required <= set(CANONICAL_STATUSES)


# ---------------------------------------------------------------------------
# Append-only; mutate rejected
# ---------------------------------------------------------------------------


def test_revision_records_append_only_mutate_rejected():
    prop, _, _, proj, _ = _svc_with_proposal()
    row = proj.apply_treasure_receipt(prop.proposal_id, _receipt("admitted"))
    with pytest.raises(ProjectionImmutable):
        proj.mutate_projection(row.projection_id, canonical_status="released")
    with pytest.raises(ProjectionImmutable):
        proj.store.update(row.projection_id, canonical_status="released")
    with pytest.raises(ProjectionImmutable):
        proj.store.delete(row.projection_id)
    # Original unchanged
    again = proj.store.get(row.projection_id)
    assert again is not None
    assert again.canonical_status == "admitted"
    # Append another
    proj.apply_treasure_receipt(prop.proposal_id, _receipt("changes_requested"))
    assert len(proj.list_revisions(prop.proposal_id)) == 2


# ---------------------------------------------------------------------------
# No seat fields / no approve endpoints that assign reviewers
# ---------------------------------------------------------------------------


def test_no_seat_fields_on_projection_dict():
    prop, _, _, proj, _ = _svc_with_proposal()
    # Seat keys in receipt are scrubbed; seat *actions* rejected
    row = proj.apply_treasure_receipt(
        prop.proposal_id,
        _receipt(
            "in_review",
            reviewer_1="alice",
            reviewer_2="bob",
            release_authority="carol",
        ),
    )
    d = row.to_dict()
    assert d["reviewer_1"] is None
    assert d["reviewer_2"] is None
    assert d["release_authority"] is None
    assert d["path_a_seats_in_threezone"] is False
    assert "alice" not in str(row.payload.get("reviewer_1"))
    assert "reviewer_1" not in row.payload


def test_seat_action_receipt_rejected():
    prop, _, _, proj, _ = _svc_with_proposal()
    with pytest.raises(InvalidTreasureReceipt):
        proj.apply_treasure_receipt(
            prop.proposal_id,
            _receipt("in_review", assign_reviewer={"seat": "r1", "actor": "alice"}),
        )


def test_gateway_has_no_approve_or_assign_reviewer_routes():
    src = (_MVP / "backend" / "ai_gateway_routes.py").read_text(encoding="utf-8")
    assert "treasure-receipt" in src
    assert "treasure-projections" in src
    # Ban seat / approve assignment endpoints for proposals
    banned = [
        r"/api/ai-proposals/.*/approve",
        r"/api/ai-proposals/.*/assign-reviewer",
        r"/api/ai-proposals/.*/assign-release",
        r"/api/ai-proposals/.*/r1",
        r"/api/ai-proposals/.*/r2",
        r"h_ai_proposal_approve",
        r"h_ai_proposal_assign",
    ]
    for pat in banned:
        assert re.search(pat, src) is None, f"banned route pattern present: {pat}"
    # Receipt handler documents ingest-not-seat
    assert "receipt_ingest_not_seat_action" in src or "not a seat" in src.lower()


# ---------------------------------------------------------------------------
# intake_accepted ≠ released
# ---------------------------------------------------------------------------


def test_intake_accepted_not_valid_canonical_status():
    with pytest.raises(InvalidTreasureReceipt) as ei:
        validate_treasure_receipt({"canonical_status": "intake_accepted"})
    assert ei.value.code == "banned_canonical_status"

    with pytest.raises(InvalidTreasureReceipt):
        validate_treasure_receipt({"canonical_status": "accepted"})

    prop, _, _, proj, _ = _svc_with_proposal()
    with pytest.raises(InvalidTreasureReceipt):
        proj.apply_treasure_receipt(
            prop.proposal_id, {"canonical_status": "intake_accepted"}
        )


def test_released_projection_does_not_set_local_treasure_release_true():
    prop, store, outbox, proj, delivery = _svc_with_proposal()
    from threezone_ai.proposals.delivery import DeliveryReceipt, HANDOFF_TYPE

    ts = time.time()
    outbox.insert(
        DeliveryReceipt(
            delivery_id="tdl_y6rel00000001",
            proposal_id=prop.proposal_id,
            job_id=prop.job_id,
            content_hash=prop.content_hash,
            handoff_type=HANDOFF_TYPE,
            payload={"treasure_release": False},
            status=STATUS_INTAKE_ACCEPTED,
            created_at=ts,
            updated_at=ts,
        )
    )
    row = proj.apply_treasure_receipt(prop.proposal_id, _receipt("released"))
    assert row.canonical_status == "released"
    assert row.to_dict()["treasure_release"] is False
    assert row.to_dict()["local_release_authority"] is False
    assert row.payload.get("treasure_release") is False
    # Proposal store flag remains false
    again = store.get(prop.proposal_id)
    assert again is not None
    assert again.treasure_release is False
    assert again.to_dict()["treasure_release"] is False
    # Delivery mirror remains false
    latest = outbox.latest_for_proposal(prop.proposal_id)
    assert latest.canonical_status == "released"
    assert latest.to_dict()["treasure_release"] is False
    assert latest.payload.get("treasure_release") is False


# ---------------------------------------------------------------------------
# Reconcile surfaces latest projection (Y5 wire)
# ---------------------------------------------------------------------------


def test_reconcile_surfaces_latest_projection():
    prop, store, outbox, proj, delivery = _svc_with_proposal()
    delivery.deliver(prop)  # skipped (moten disabled) — still ok for reconcile
    before = delivery.reconcile(prop)
    assert before.get("latest_revision_projection") is None
    assert before["treasure_release"] is False

    proj.apply_treasure_receipt(prop.proposal_id, _receipt("admitted"))
    proj.apply_treasure_receipt(prop.proposal_id, _receipt("in_review"))
    after = delivery.reconcile(prop)
    assert after["canonical_status"] == "in_review"
    assert after["canonical_packet_id"] == "pkt_treasure_y6_001"
    assert after["latest_revision_projection"]["canonical_status"] == "in_review"
    assert after["treasure_release"] is False
    assert after["path_a_seats_in_threezone"] is False
    assert after["reviewer_1"] is None


def test_projection_summary_operator_view():
    prop, _, _, proj, _ = _svc_with_proposal()
    proj.apply_treasure_receipt(prop.proposal_id, _receipt("admitted"))
    proj.apply_treasure_receipt(prop.proposal_id, _receipt("rejected"))
    summary = proj.projection_summary(prop.proposal_id)
    assert summary["revision_count"] == 2
    assert summary["canonical_status"] == "rejected"
    assert summary["treasure_release"] is False
    assert summary["schema_ref"] == PROJECTION_SCHEMA_REF
    assert set(summary["allowed_statuses"]) == set(CANONICAL_STATUSES)


# ---------------------------------------------------------------------------
# Docs + static bans
# ---------------------------------------------------------------------------


def test_y6_doc_exists_and_states_projections_only():
    doc = Path(__file__).resolve().parents[2] / "docs" / "multi-ai" / "Y6-REVIEW-PROJECTIONS.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "projections" in text.lower()
    assert "seats" in text.lower()
    assert "Treasure" in text
    assert "intake_accepted" in text
    assert "treasure_release" in text
    assert "R1" in text or "Reviewer" in text or "seat" in text.lower()
    assert "append-only" in text.lower() or "INSERT only" in text


def test_projections_module_no_cloud_sdk_imports():
    forbidden = {"groq", "openai", "google.generativeai", "ollama"}
    path = _MVP / "threezone_ai" / "proposals" / "projections.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
            assert not node.module.startswith("threezone_ai.providers")


def test_changes_requested_corrected_superseded():
    prop, _, _, proj, _ = _svc_with_proposal()
    for status in ("changes_requested", "corrected", "superseded"):
        row = proj.apply_treasure_receipt(prop.proposal_id, _receipt(status))
        assert row.canonical_status == status
    assert len(proj.list_revisions(prop.proposal_id)) == 3
