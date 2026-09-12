"""Y5 — Treasure delivery + reconciliation (Path A producer handoff plumbing).

Delivery ≠ release. Bare accepted banned for governance. No ControlPlane seats.
"""

from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.proposals import (
    DELIVERY_SCHEMA,
    HANDOFF_TYPE,
    PACKET_FAMILY,
    PACKET_TYPE,
    PROPOSAL_SCHEMA_REF,
    STATUS_INTAKE_ACCEPTED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    AiProposalStore,
    ProposeService,
    TreasureDeliveryOutbox,
    TreasureDeliveryService,
    build_delivery_payload,
    content_hash_for_segments,
    reset_delivery_service,
    reset_propose_service,
)
from threezone_ai.proposals.types import TranscriptionProposal
from threezone_ai.config import reset_settings


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    monkeypatch.delenv("TZ_MOTEN_SERVICE_URL", raising=False)
    monkeypatch.delenv("TZ_MOTEN_SHARED_SECRET", raising=False)
    reset_settings()
    reset_propose_service()
    reset_delivery_service()
    yield
    reset_settings()
    reset_propose_service()
    reset_delivery_service()
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    monkeypatch.delenv("TZ_MOTEN_SERVICE_URL", raising=False)


def _enable_process(monkeypatch) -> None:
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    reset_settings()


def _sample_proposal(**overrides) -> TranscriptionProposal:
    segs = [
        {"start": 0.0, "end": 1.5, "text": "hello treasure", "speaker": "a"},
        {"start": 1.5, "end": 3.0, "text": "path a producer", "speaker": None},
    ]
    base = dict(
        proposal_id="aip_y5test00000001",
        job_id="aij_y5job00000001",
        source_asset_id="asset:synthetic:y5-001",
        segments=segs,
        content_hash=content_hash_for_segments(segs),
        created_at=time.time(),
        status="proposed",
        schema_ref=PROPOSAL_SCHEMA_REF,
        publish=False,
        treasure_release=False,
        human_review_required=True,
        provider="transcription_local",
        lineage_id="lin_y5lineage0001",
    )
    base.update(overrides)
    return TranscriptionProposal(**base)


def _mock_intake_http(url, body, secret, timeout):
    payload = json.loads(body.decode("utf-8"))
    assert payload.get("treasure_release") is False
    assert payload.get("publish") is False
    return (
        202,
        {
            "intake_accepted": True,
            "accepted": True,  # legacy alias only
            "status": "intake_accepted",
            "means": "transport_receipt_only",
            "governance": "none",
            "intake_id": "EVD_mock_001",
            "source_object_id": payload.get("proposal_id"),
        },
    )


# ---------------------------------------------------------------------------
# Payload completeness (Path A producer handoff)
# ---------------------------------------------------------------------------


def test_delivery_payload_complete_path_a_producer_fields():
    prop = _sample_proposal()
    payload = build_delivery_payload(
        prop,
        producer={"actor": "demo-owner", "role": "producer"},
        lineage={"provider": "transcription_local", "model": "local-ci", "version": "1"},
        job_result={"provider": "transcription_local", "model": "local-ci", "version": "1"},
    )
    assert payload["schema"] == DELIVERY_SCHEMA
    assert payload["handoff_type"] == HANDOFF_TYPE
    assert payload["packet_family"] == PACKET_FAMILY
    assert payload["packet_type"] == PACKET_TYPE
    assert payload["proposal_id"] == prop.proposal_id
    assert payload["job_id"] == prop.job_id
    assert payload["source_asset_id"] == prop.source_asset_id
    assert payload["content_hash"] == prop.content_hash
    assert payload["content_hash"].startswith("sha256:")
    assert payload["segments"] == prop.segments
    assert payload["segments_ref"] == f"proposal:{prop.proposal_id}:segments"
    assert payload["proposal_schema_ref"] == PROPOSAL_SCHEMA_REF
    assert payload["publish"] is False
    assert payload["treasure_release"] is False
    assert payload["producer"]["role"] == "producer"
    assert payload["producer"]["actor"] == "demo-owner"
    assert payload["lineage"]["provider"] == "transcription_local"
    assert payload["lineage"]["model"] == "local-ci"
    assert payload["lineage"]["version"] == "1"
    assert payload["lineage"]["lineage_id"] == prop.lineage_id
    assert payload["provenance"]["content_hash"] == prop.content_hash
    assert payload["delivery_state"] == "submitted"
    assert payload["canonical_packet_id"] is None
    assert payload["canonical_revision_id"] is None
    assert payload["canonical_status"] is None
    assert payload["path_a"]["seats_in_threezone"] is False
    assert payload["governance"] == "none"
    # Ban: no review seat fields on producer handoff
    assert "reviewer_1" not in payload
    assert "reviewer_2" not in payload
    assert "release_authority" not in payload


# ---------------------------------------------------------------------------
# Deliver → outbox + intake_accepted
# ---------------------------------------------------------------------------


def test_deliver_proposal_outbox_intake_accepted():
    prop = _sample_proposal()
    store = AiProposalStore(":memory:")
    store.insert(prop)
    outbox = TreasureDeliveryOutbox(":memory:")
    svc = TreasureDeliveryService(
        outbox,
        propose_get=store.get,
        moten_service_url="http://moten.test",
        moten_shared_secret="secret",
        http_post=_mock_intake_http,
    )
    receipt = svc.deliver(prop, sync=True)
    assert receipt.status == STATUS_INTAKE_ACCEPTED
    assert receipt.to_dict()["intake_accepted"] is True
    assert receipt.to_dict()["treasure_release"] is False
    assert receipt.payload["treasure_release"] is False
    assert receipt.payload["publish"] is False
    assert receipt.payload["packet_family"] == PACKET_FAMILY
    assert receipt.payload["packet_type"] == PACKET_TYPE
    assert receipt.payload["content_hash"] == prop.content_hash
    assert receipt.response_metadata.get("intake_accepted") is True
    assert receipt.to_dict()["governance"] == "none"
    assert receipt.to_dict()["means"] == "intake_accepted_transport_only"


def test_deliver_disabled_moten_skipped_honest():
    prop = _sample_proposal()
    outbox = TreasureDeliveryOutbox(":memory:")
    svc = TreasureDeliveryService(outbox, moten_service_url="")
    receipt = svc.deliver(prop, sync=True)
    assert receipt.status == STATUS_SKIPPED
    assert receipt.last_error == "moten service not configured"
    assert receipt.to_dict()["treasure_release"] is False
    assert receipt.to_dict()["intake_accepted"] is False


def test_never_treasure_release_true():
    prop = _sample_proposal()
    outbox = TreasureDeliveryOutbox(":memory:")
    svc = TreasureDeliveryService(
        outbox,
        moten_service_url="http://moten.test",
        http_post=_mock_intake_http,
    )
    receipt = svc.deliver(prop)
    d = receipt.to_dict()
    assert d["treasure_release"] is False
    assert receipt.payload["treasure_release"] is False
    assert receipt.payload.get("publish") is False


def test_never_bare_accepted_as_governance_status():
    prop = _sample_proposal()
    outbox = TreasureDeliveryOutbox(":memory:")
    svc = TreasureDeliveryService(
        outbox,
        moten_service_url="http://moten.test",
        http_post=_mock_intake_http,
    )
    receipt = svc.deliver(prop)
    d = receipt.to_dict()
    assert d["status"] == STATUS_INTAKE_ACCEPTED
    assert d["status"] != "accepted"
    assert "accepted" not in d or d.get("accepted") is not True  # must not be top-level governance
    assert d["intake_accepted"] is True
    assert d["governance"] == "none"
    # response may contain legacy alias, but status field must be intake_accepted
    body = d.get("response_body") or {}
    if isinstance(body, dict) and "accepted" in body:
        assert body.get("status") == "intake_accepted"
        assert body.get("intake_accepted") is True


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------


def test_reconcile_pending_vs_intake_accepted():
    prop = _sample_proposal()
    store = AiProposalStore(":memory:")
    store.insert(prop)
    outbox = TreasureDeliveryOutbox(":memory:")
    svc = TreasureDeliveryService(
        outbox,
        propose_get=store.get,
        moten_service_url="http://moten.test",
        http_post=_mock_intake_http,
    )

    before = svc.reconcile(prop)
    assert before["reconcile_status"] == STATUS_PENDING
    assert before["delivery_state"] == "submitted"
    assert before["intake_accepted"] is False
    assert before["treasure_release"] is False
    assert before["path_a_seats_in_threezone"] is False
    assert before["reviewer_1"] is None
    assert before["reviewer_2"] is None
    assert before["release_authority"] is None

    svc.deliver(prop)
    after = svc.reconcile(prop)
    assert after["reconcile_status"] == STATUS_INTAKE_ACCEPTED
    assert after["delivery_state"] == "intake_accepted"
    assert after["intake_accepted"] is True
    assert after["treasure_release"] is False
    assert after["packet_family"] == PACKET_FAMILY
    assert after["packet_type"] == PACKET_TYPE
    assert after["content_hash"] == prop.content_hash


def test_reconcile_skipped_when_moten_disabled():
    prop = _sample_proposal()
    svc = TreasureDeliveryService(TreasureDeliveryOutbox(":memory:"), moten_service_url="")
    svc.deliver(prop)
    report = svc.reconcile(prop)
    assert report["reconcile_status"] == STATUS_SKIPPED
    assert report["moten_enabled"] is False


# ---------------------------------------------------------------------------
# Idempotent deliver
# ---------------------------------------------------------------------------


def test_idempotent_deliver():
    calls = {"n": 0}

    def counting_http(url, body, secret, timeout):
        calls["n"] += 1
        return _mock_intake_http(url, body, secret, timeout)

    prop = _sample_proposal()
    svc = TreasureDeliveryService(
        TreasureDeliveryOutbox(":memory:"),
        moten_service_url="http://moten.test",
        http_post=counting_http,
    )
    r1 = svc.deliver(prop)
    r2 = svc.deliver(prop)
    assert r1.delivery_id == r2.delivery_id
    assert r1.status == STATUS_INTAKE_ACCEPTED
    assert r2.status == STATUS_INTAKE_ACCEPTED
    assert calls["n"] == 1  # second deliver did not re-POST


def test_force_redeliver_creates_new_attempt():
    calls = {"n": 0}

    def counting_http(url, body, secret, timeout):
        calls["n"] += 1
        return _mock_intake_http(url, body, secret, timeout)

    prop = _sample_proposal()
    svc = TreasureDeliveryService(
        TreasureDeliveryOutbox(":memory:"),
        moten_service_url="http://moten.test",
        http_post=counting_http,
    )
    r1 = svc.deliver(prop)
    r2 = svc.deliver(prop, force=True)
    assert r1.delivery_id != r2.delivery_id
    assert r2.status == STATUS_INTAKE_ACCEPTED
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# No ControlPlane review seats / isolation
# ---------------------------------------------------------------------------


def test_no_controlplane_review_seats_invented():
    prop = _sample_proposal()
    svc = TreasureDeliveryService(
        TreasureDeliveryOutbox(":memory:"),
        moten_service_url="http://moten.test",
        http_post=_mock_intake_http,
    )
    receipt = svc.deliver(prop)
    report = svc.reconcile(prop)
    for obj in (receipt.to_dict(), report, receipt.payload):
        assert obj.get("treasure_release") is False or "treasure_release" not in obj or obj["treasure_release"] is False
        for banned in (
            "reviewer_1",
            "reviewer_2",
            "release_authority",
            "r1_seat",
            "r2_seat",
            "path_a_release",
        ):
            # reconcile explicitly sets seats to None; payload must not invent them as active seats
            if banned in obj and obj[banned] is not None:
                pytest.fail(f"invented seat field {banned}={obj[banned]!r}")
        assert obj.get("path_a_seats_in_threezone") in (False, None)


def test_delivery_outbox_isolated_from_control_plane_tables():
    outbox = TreasureDeliveryOutbox(":memory:")
    names = {
        r[0]
        for r in outbox._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "treasure_delivery_outbox" in names
    assert "lease_records" not in names
    assert "rights" not in names
    assert "settlements" not in names
    assert "events" not in names


def test_failed_transport_reconciles_failed():
    def boom(url, body, secret, timeout):
        raise ConnectionError("refused")

    prop = _sample_proposal()
    svc = TreasureDeliveryService(
        TreasureDeliveryOutbox(":memory:"),
        moten_service_url="http://moten.test",
        http_post=boom,
    )
    receipt = svc.deliver(prop)
    assert receipt.status == "failed"
    report = svc.reconcile(prop)
    assert report["reconcile_status"] == "failed"
    assert report["intake_accepted"] is False
    assert report["treasure_release"] is False


def test_http_routes_registered():
    from backend.ai_gateway_routes import extra_routes

    routes = extra_routes()
    by_handler = {r[2]: r for r in routes}
    assert "h_ai_proposal_deliver" in by_handler
    assert "h_ai_proposal_reconcile" in by_handler
    assert by_handler["h_ai_proposal_deliver"][0] == "POST"
    assert by_handler["h_ai_proposal_reconcile"][0] == "GET"
    assert by_handler["h_ai_proposal_deliver"][3] == "operator"
    assert by_handler["h_ai_proposal_deliver"][1].search(
        "/api/ai-proposals/aip_abc123/deliver"
    )
    assert by_handler["h_ai_proposal_reconcile"][1].search(
        "/api/ai-proposals/aip_abc123/reconcile"
    )


def test_y5_doc_exists_and_states_delivery_ne_release():
    doc = Path(__file__).resolve().parents[2] / "docs" / "multi-ai" / "Y5-TREASURE-DELIVERY.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "intake_accepted" in text
    assert "Delivery ≠ release" in text or "delivery ≠ release" in text.lower()
    assert "THREEZONE_MEDIA_TRANSCRIPT" in text
    assert "never invent" in text.lower() or "never invent" in text
    assert "Treasure" in text
    assert "bare" in text.lower() and "accepted" in text


def test_moten_adapter_proposal_handoff_sets_intake_accepted_status_name():
    """Static: MotenIntakeService records intake_accepted for transcription-proposal."""
    src = (_MVP / "backend" / "moten_adapter.py").read_text(encoding="utf-8")
    assert "handoff_transcription_proposal" in src
    assert "intake_accepted" in src
    assert "transcription-proposal" in src


def test_delivery_module_no_cloud_sdk_imports():
    forbidden = {"groq", "openai", "google.generativeai", "ollama"}
    path = _MVP / "threezone_ai" / "proposals" / "delivery.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
            assert not node.module.startswith("threezone_ai.providers")


def test_propose_then_deliver_roundtrip(monkeypatch):
    _enable_process(monkeypatch)
    from threezone_ai.jobs.types import AiJob

    segs = [{"start": 0.0, "end": 1.0, "text": "roundtrip", "speaker": None}]
    job = AiJob(
        job_id="aij_y5roundtrip001",
        task_type="transcription",
        source_asset_id="asset:synthetic:rt",
        status="succeeded",
        result={
            "ok": True,
            "segments": segs,
            "provider": "transcription_local",
            "model": "ci",
            "version": "0",
        },
        created_at=time.time(),
        updated_at=time.time(),
        lineage_id="lin_rt001",
    )
    propose = ProposeService(AiProposalStore(":memory:"))
    prop = propose.propose_from_job(job)
    assert prop.treasure_release is False

    svc = TreasureDeliveryService(
        TreasureDeliveryOutbox(":memory:"),
        propose_get=propose.get,
        moten_service_url="http://moten.test",
        http_post=_mock_intake_http,
    )
    receipt = svc.deliver(
        prop,
        producer={"actor": "operator-1"},
        lineage={"provider": "transcription_local", "model": "ci", "version": "0"},
        job_result=job.result,
    )
    assert receipt.status == STATUS_INTAKE_ACCEPTED
    assert receipt.payload["packet_type"] == PACKET_TYPE
    assert receipt.payload["job_id"] == job.job_id
    assert receipt.payload["lineage"]["provider"] == "transcription_local"
    report = svc.reconcile(prop.proposal_id)
    assert report["reconcile_status"] == STATUS_INTAKE_ACCEPTED
