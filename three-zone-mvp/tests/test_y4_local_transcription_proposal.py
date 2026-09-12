"""Y4 — local transcription path + immutable proposal (≠ Treasure release)."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.config import Settings, reset_settings
from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG
from threezone_ai.jobs import AiJobService, AiJobStore, AiDisabled
from threezone_ai.jobs.types import TRANSCRIPTION_SEGMENTS_SCHEMA_REF
from threezone_ai.proposals import (
    PROPOSAL_SCHEMA_REF,
    AiDisabledForPropose,
    AiProposalStore,
    ProposeService,
    ProposalImmutable,
    content_hash_for_segments,
    reset_propose_service,
)
from threezone_ai.providers.base import get_provider_registry, reset_provider_registry
from threezone_ai.types import AIRequest, AIResponse, TaskType


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    reset_settings()
    reset_provider_registry()
    reset_propose_service()
    yield
    reset_settings()
    reset_provider_registry()
    reset_propose_service()
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)


def _enable_process(monkeypatch) -> None:
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    reset_settings()


def _enable_gateway(monkeypatch):
    _enable_process(monkeypatch)
    cfg = deepcopy(DEFAULT_GATEWAY_CONFIG)
    cfg["enabled"] = True
    enabled = Settings(ai_enabled=True, gateway_config=cfg)
    monkeypatch.setattr(
        "threezone_ai.gateway.get_settings",
        lambda reload=False, _s=enabled: _s,
    )
    monkeypatch.setattr(
        "threezone_ai.config.get_settings",
        lambda reload=False, _s=enabled: _s,
    )
    return cfg


def _svc_with_propose() -> tuple[AiJobService, ProposeService]:
    job_store = AiJobStore(":memory:")
    prop_store = AiProposalStore(":memory:")
    propose = ProposeService(prop_store, job_store=job_store)
    svc = AiJobService(
        job_store,
        propose_service=propose,
        auto_propose=True,
    )
    return svc, propose


def test_ai_off_no_propose(monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "0")
    reset_settings()
    job_store = AiJobStore(":memory:")
    # Seed a fake succeeded job without going through admit (AI off).
    from threezone_ai.jobs.types import AiJob
    import time

    job = AiJob(
        job_id="aij_offpropose0001",
        task_type="transcription",
        source_asset_id="asset:synthetic:off",
        status="succeeded",
        result={
            "ok": True,
            "segments": [{"start": 0.0, "end": 1.0, "text": "x", "speaker": None}],
            "publish": False,
            "treasure_release": False,
        },
        created_at=time.time(),
        updated_at=time.time(),
    )
    job_store.insert(job)
    propose = ProposeService(AiProposalStore(":memory:"), job_store=job_store)
    with pytest.raises(AiDisabledForPropose):
        propose.propose_from_job(job)
    assert propose.get_by_job(job.job_id) is None


def test_local_path_job_creates_proposal_with_hash(monkeypatch):
    _enable_gateway(monkeypatch)
    svc, propose = _svc_with_propose()
    job = svc.admit("transcription", "asset:synthetic:y4-local-001")
    t0 = 20_000.0
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=t0)
    done = svc.run(job.job_id, "worker-a", now=t0 + 1, record_lineage=False)
    assert done.status == "succeeded"
    assert done.result.get("provider") == "transcription_local"
    assert done.result.get("local_path") is True
    assert int(done.result.get("segment_count") or 0) >= 1
    assert done.result.get("proposal_id")

    prop = propose.get_by_job(job.job_id)
    assert prop is not None
    assert prop.proposal_id.startswith("aip_")
    assert prop.job_id == job.job_id
    assert prop.source_asset_id == "asset:synthetic:y4-local-001"
    assert prop.schema_ref == PROPOSAL_SCHEMA_REF
    assert prop.status == "proposed"
    assert prop.content_hash.startswith("sha256:")
    assert prop.verify_hash() is True
    assert prop.content_hash == content_hash_for_segments(prop.segments)
    assert len(prop.segments) >= 1


def test_mutation_rejected_and_verify_hash_fails_if_tampered(monkeypatch):
    _enable_process(monkeypatch)
    store = AiProposalStore(":memory:")
    propose = ProposeService(store)
    from threezone_ai.jobs.types import AiJob
    import time

    segs = [
        {"start": 0.0, "end": 1.5, "text": "immutable", "speaker": "a"},
        {"start": 1.5, "end": 3.0, "text": "proposal", "speaker": None},
    ]
    job = AiJob(
        job_id="aij_mut0000000001",
        task_type="transcription",
        source_asset_id="asset:synthetic:mut",
        status="succeeded",
        result={"ok": True, "segments": segs, "provider": "transcription_local"},
        created_at=time.time(),
        updated_at=time.time(),
    )
    prop = propose.propose_from_job(job)
    assert prop.verify_hash() is True

    with pytest.raises(ProposalImmutable):
        propose.mutate_payload(
            prop.proposal_id,
            [{"start": 0.0, "end": 9.0, "text": "TAMPERED", "speaker": None}],
        )
    with pytest.raises(ProposalImmutable):
        store.update_payload(prop.proposal_id, [{"text": "nope"}], "sha256:dead")

    # Simulate tamper by mutating in-memory object (store untouched).
    tampered = propose.get(prop.proposal_id)
    tampered.segments = list(tampered.segments) + [
        {"start": 9.0, "end": 10.0, "text": "extra", "speaker": None}
    ]
    assert tampered.verify_hash() is False
    # Stored row still verifies.
    assert propose.get(prop.proposal_id).verify_hash() is True


def test_publish_false_no_treasure_release(monkeypatch):
    _enable_gateway(monkeypatch)
    svc, propose = _svc_with_propose()
    job = svc.admit("transcription", "asset:synthetic:y4-flags")
    svc.claim(job.job_id, "w1", ttl_s=60, now=1.0)
    done = svc.run(job.job_id, "w1", now=2.0, record_lineage=False)
    prop = propose.get_by_job(job.job_id)
    assert prop is not None
    d = prop.to_dict()
    assert d["publish"] is False
    assert d["treasure_release"] is False
    assert d["human_review_required"] is True
    assert done.publish is False
    assert done.treasure_release is False
    assert done.result.get("publish") is False
    assert done.result.get("treasure_release") is False


def test_gateway_only_no_direct_cloud_sdk():
    """Static: proposals + jobs + backend do not import cloud SDKs / providers."""
    forbidden = {
        "groq",
        "openai",
        "google.generativeai",
        "ollama",
        "faster_whisper",
    }
    roots = [
        _MVP / "backend",
        _MVP / "threezone_ai" / "jobs",
        _MVP / "threezone_ai" / "proposals",
    ]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if alias.name in forbidden or top in forbidden:
                            offenders.append(f"{path}:{alias.name}")
                        if alias.name.startswith("threezone_ai.providers"):
                            offenders.append(f"{path}:{alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module in forbidden or node.module.split(".")[0] in forbidden:
                        offenders.append(f"{path}:{node.module}")
                    if node.module.startswith("threezone_ai.providers"):
                        offenders.append(f"{path}:{node.module}")
    assert not offenders, f"direct AI SDK / provider imports: {offenders}"

    local_src = (_MVP / "threezone_ai" / "providers" / "transcription_local.py").read_text(
        encoding="utf-8"
    )
    assert "groq" not in local_src.lower() or "never" in local_src.lower()
    assert "gemini" not in local_src.lower() or "never" in local_src.lower()
    assert "is_local = True" in local_src
    assert "transcription_local" in local_src


def test_transcription_local_registered_ahead_of_offline():
    reg = get_provider_registry()
    assert "transcription_local" in reg
    assert reg["transcription_local"].is_local is True
    assert DEFAULT_GATEWAY_CONFIG["tasks"]["transcription"]["default_order"][0] == (
        "transcription_local"
    )
    assert "transcription_offline" in DEFAULT_GATEWAY_CONFIG["tasks"]["transcription"][
        "default_order"
    ]


def test_explicit_propose_api_idempotent(monkeypatch):
    _enable_process(monkeypatch)
    job_store = AiJobStore(":memory:")
    propose = ProposeService(AiProposalStore(":memory:"), job_store=job_store)
    svc = AiJobService(job_store, propose_service=propose, auto_propose=False)

    def _fake_run(request: AIRequest, **_kw) -> AIResponse:
        return AIResponse(
            ok=True,
            task_type=TaskType.TRANSCRIPTION.value,
            provider="transcription_local",
            segments=[
                {"start": 0.0, "end": 1.0, "text": "hello", "speaker": None},
            ],
            metadata={
                "schema_version": TRANSCRIPTION_SEGMENTS_SCHEMA_REF,
                "local_path": True,
                "is_local": True,
                "publish": False,
            },
            human_review_required=True,
        )

    svc._gateway_run = _fake_run
    job = svc.admit("transcription", "asset:synthetic:idem")
    svc.claim(job.job_id, "w", ttl_s=60, now=5.0)
    done = svc.run(job.job_id, "w", now=6.0)
    assert done.result.get("proposal_id") is None  # auto_propose off
    p1 = svc.propose(job.job_id, now=7.0)
    p2 = svc.propose(job.job_id, now=8.0)
    assert p1.proposal_id == p2.proposal_id
    assert p1.content_hash == p2.content_hash


def test_content_hash_canonical_stable():
    segs = [
        {"end": 2.0, "start": 0.0, "text": "a", "speaker": None},
        {"speaker": "x", "text": "b", "end": 4.0, "start": 2.0},
    ]
    h1 = content_hash_for_segments(segs)
    h2 = content_hash_for_segments(
        [
            {"start": 0.0, "end": 2.0, "text": "a", "speaker": None},
            {"start": 2.0, "end": 4.0, "text": "b", "speaker": "x"},
        ]
    )
    assert h1 == h2
    raw = json.dumps(segs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert h1 == "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_http_propose_route_registered():
    from backend.ai_gateway_routes import extra_routes

    routes = extra_routes()
    by_handler = {r[2]: r for r in routes}
    assert "h_ai_jobs_propose" in by_handler
    assert by_handler["h_ai_jobs_propose"][0] == "POST"
    assert by_handler["h_ai_jobs_propose"][3] == "operator"
    assert by_handler["h_ai_jobs_propose"][1].search(
        "/api/ai-jobs/aij_abc123/propose"
    )


def test_http_propose_503_when_ai_off(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    from backend import ai_gateway_routes as routes

    class _H:
        def __init__(self):
            self.status = None
            self.payload = None
            self._require_ai = routes.AiGatewayHandlers._require_ai.__get__(self, _H)
            self.h_ai_jobs_propose = routes.AiGatewayHandlers.h_ai_jobs_propose.__get__(
                self, _H
            )

        def _send_json(self, status, payload):
            self.status = status
            self.payload = payload

    h = _H()
    h.h_ai_jobs_propose({"job_id": "aij_x"}, {}, None)
    assert h.status == 503
    assert h.payload == {"error": "ai_disabled", "code": "ai_disabled"}


def test_proposals_store_isolated_from_control_plane(monkeypatch):
    _enable_process(monkeypatch)
    store = AiProposalStore(":memory:")
    names = {
        r[0]
        for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "ai_proposals" in names
    assert "lease_records" not in names
    assert "rights" not in names
    assert "settlements" not in names
