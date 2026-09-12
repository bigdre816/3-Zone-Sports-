"""Y3 — durable AI jobs / admission / worker leases (not playback leases)."""

from __future__ import annotations

import ast
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.config import Settings, reset_settings
from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG
from threezone_ai.jobs import (
    ADMIT_TASKS,
    DEFAULT_LEASE_TTL_S,
    MAX_LEASE_TTL_S,
    MIN_LEASE_TTL_S,
    TRANSCRIPTION_SEGMENTS_SCHEMA_REF,
    AiDisabled,
    AiJobService,
    AiJobStore,
    JobConflict,
    LeaseConflict,
    TaskNotAllowlisted,
    bound_lease_ttl_s,
)
from threezone_ai.jobs.types import InvalidWorkLease
from threezone_ai.providers.base import reset_provider_registry
from threezone_ai.types import AIRequest, AIResponse, TaskType


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    reset_settings()
    reset_provider_registry()
    yield
    reset_settings()
    reset_provider_registry()
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)


def _svc() -> AiJobService:
    return AiJobService(AiJobStore(":memory:"))


def _enable_process(monkeypatch) -> None:
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    reset_settings()


def _enable_gateway(monkeypatch):
    """Process gate + settings/config so gateway.run can reach the fake provider."""
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


def test_ai_off_admit_fails(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "0")
    svc = _svc()
    with pytest.raises(AiDisabled) as ctx:
        svc.admit(TaskType.TRANSCRIPTION, "asset:synthetic:transcription-001")
    assert ctx.value.code == "ai_disabled"
    assert ctx.value.status == 503


def test_ai_unset_admit_fails_fail_closed(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    svc = _svc()
    with pytest.raises(AiDisabled):
        svc.admit("transcription", "asset:synthetic:off")


def test_admit_transcription_when_on(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    job = svc.admit(
        TaskType.TRANSCRIPTION,
        "asset:synthetic:basketball-001",
        payload={"privacy_class": "member"},
    )
    assert job.job_id.startswith("aij_")
    assert job.task_type == "transcription"
    assert job.status == "admitted"
    assert job.source_asset_id == "asset:synthetic:basketball-001"
    assert job.publish is False
    assert job.treasure_release is False
    assert job.lease_owner is None
    fetched = svc.get(job.job_id)
    assert fetched.job_id == job.job_id
    assert fetched.to_dict()["lease_kind"] == "ai_work_lease"


def test_admit_rejects_non_allowlisted_task(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    with pytest.raises(TaskNotAllowlisted):
        svc.admit(TaskType.CAPTION, "asset:synthetic:caption")
    with pytest.raises(TaskNotAllowlisted):
        svc.admit(TaskType.SPORTS_VISION, "asset:synthetic:vision")
    assert "transcription" in ADMIT_TASKS
    assert "caption" not in ADMIT_TASKS


def test_lease_claim_double_claim_blocked_expiry_reclaim(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:lease-001")
    t0 = 1_700_000_000.0

    claimed = svc.claim(job.job_id, "worker-a", ttl_s=60, now=t0)
    assert claimed.status == "leased"
    assert claimed.lease_owner == "worker-a"
    assert claimed.lease_expires_at == t0 + 60
    assert claimed.to_dict()["lease_kind"] == "ai_work_lease"

    with pytest.raises(LeaseConflict):
        svc.claim(job.job_id, "worker-b", ttl_s=60, now=t0 + 10)

    # Same worker may refresh while holding.
    again = svc.claim(job.job_id, "worker-a", ttl_s=60, now=t0 + 15)
    assert again.lease_owner == "worker-a"
    assert again.lease_expires_at == t0 + 15 + 60

    # After expiry, another worker can reclaim.
    reclaimed = svc.claim(job.job_id, "worker-b", ttl_s=60, now=t0 + 15 + 60 + 1)
    assert reclaimed.lease_owner == "worker-b"
    assert reclaimed.status == "leased"


def test_heartbeat_renews_only_holder(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:hb-001")
    t0 = 5_000.0
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=t0)
    renewed = svc.heartbeat(job.job_id, "worker-a", ttl_s=60, now=t0 + 20)
    assert renewed.lease_expires_at == t0 + 20 + 60
    with pytest.raises(InvalidWorkLease):
        svc.heartbeat(job.job_id, "worker-b", ttl_s=60, now=t0 + 21)
    # Expired lease cannot heartbeat — must reclaim.
    with pytest.raises(InvalidWorkLease):
        svc.heartbeat(job.job_id, "worker-a", ttl_s=60, now=t0 + 20 + 60 + 1)


def test_lease_ttl_is_bounded():
    assert bound_lease_ttl_s(None) == DEFAULT_LEASE_TTL_S
    assert bound_lease_ttl_s(60) == 60
    assert bound_lease_ttl_s(1) == MIN_LEASE_TTL_S
    assert bound_lease_ttl_s(10_000) == MAX_LEASE_TTL_S
    assert DEFAULT_LEASE_TTL_S == 60


def test_complete_via_gateway_fake_provider_publish_false(monkeypatch):
    _enable_gateway(monkeypatch)
    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:basketball-001")
    t0 = 9_000.0
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=t0)
    done = svc.run(job.job_id, "worker-a", now=t0 + 1, record_lineage=False)
    assert done.status == "succeeded"
    assert done.publish is False
    assert done.treasure_release is False
    assert done.result_schema_ref == TRANSCRIPTION_SEGMENTS_SCHEMA_REF
    assert done.result is not None
    assert done.result.get("publish") is False
    assert done.result.get("treasure_release") is False
    assert done.result.get("provider") == "transcription_local"
    assert done.result.get("ok") is True
    assert int(done.result.get("segment_count") or 0) >= 1


def test_complete_helper_forces_publish_false(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:complete-001")
    t0 = 11_000.0
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=t0)
    done = svc.complete(
        job.job_id,
        "worker-a",
        result={"publish": True, "treasure_release": True, "ok": True},
        now=t0 + 1,
    )
    assert done.status == "succeeded"
    assert done.publish is False
    assert done.treasure_release is False
    assert done.result["publish"] is False
    assert done.result["treasure_release"] is False
    assert done.result_schema_ref == TRANSCRIPTION_SEGMENTS_SCHEMA_REF


def test_run_without_lease_blocked(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:nolease")
    with pytest.raises(InvalidWorkLease):
        svc.run(job.job_id, "worker-a", now=1.0, record_lineage=False)


def test_run_when_ai_off_blocked(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:later-off")
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=1.0)
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "0")
    reset_settings()
    with pytest.raises(AiDisabled):
        svc.run(job.job_id, "worker-a", now=2.0, record_lineage=False)


def test_no_playback_lease_records_mutation(monkeypatch):
    """AI job admit/claim/run must not write ControlPlane playback leases."""
    from backend.db import Database
    from backend.seed import seed_if_empty

    _enable_gateway(monkeypatch)
    db = Database(":memory:")
    seed_if_empty(db)
    snapshots = {
        "lease_records": db.query("SELECT * FROM lease_records"),
        "rights": db.query("SELECT event_id, version, active, revoked FROM rights"),
        "settlements": db.query("SELECT * FROM settlements"),
        "xrpl_publications": db.query("SELECT * FROM xrpl_publications"),
        "moten_outbox": db.query("SELECT * FROM moten_outbox"),
        "events_score": db.query("SELECT event_id, scoreboard, status FROM events"),
    }

    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:no-playback")
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=100.0)
    svc.run(job.job_id, "worker-a", now=101.0, record_lineage=False)

    for table, before in snapshots.items():
        after = {
            "lease_records": db.query("SELECT * FROM lease_records"),
            "rights": db.query("SELECT event_id, version, active, revoked FROM rights"),
            "settlements": db.query("SELECT * FROM settlements"),
            "xrpl_publications": db.query("SELECT * FROM xrpl_publications"),
            "moten_outbox": db.query("SELECT * FROM moten_outbox"),
            "events_score": db.query("SELECT event_id, scoreboard, status FROM events"),
        }[table]
        assert [dict(r) for r in after] == [dict(r) for r in before], table

    # Isolated store has no lease_records table at all.
    names = {
        r[0]
        for r in svc.store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "ai_jobs" in names
    assert "lease_records" not in names


def test_job_runner_calls_gateway_not_providers(monkeypatch):
    _enable_process(monkeypatch)
    calls: list[str] = []

    def _fake_run(request: AIRequest, **_kw) -> AIResponse:
        calls.append(request.normalized_task().value)
        return AIResponse(
            ok=True,
            task_type=TaskType.TRANSCRIPTION.value,
            provider="transcription_offline",
            segments=[{"start": 0.0, "end": 1.0, "text": "hi", "speaker": None}],
            metadata={
                "schema_version": TRANSCRIPTION_SEGMENTS_SCHEMA_REF,
                "publish": False,
            },
        )

    def _boom_registry():
        raise AssertionError("provider registry must not be touched by job runner")

    monkeypatch.setattr(
        "threezone_ai.providers.base.get_provider_registry",
        _boom_registry,
    )
    svc = AiJobService(AiJobStore(":memory:"), gateway_run=_fake_run)
    job = svc.admit("transcription", "asset:synthetic:gw-only")
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=50.0)
    done = svc.run(job.job_id, "worker-a", now=51.0, record_lineage=False)
    assert calls == ["transcription"]
    assert done.status == "succeeded"
    assert done.result["provider"] == "transcription_offline"
    assert done.result["publish"] is False


def test_forbid_path_still_gateway_only():
    """Static check: jobs + backend must not import cloud SDKs or providers."""
    forbidden = {
        "groq",
        "openai",
        "google.generativeai",
        "ollama",
        "faster_whisper",
    }
    forbidden_from_prefixes = ("threezone_ai.providers",)
    roots = [
        _MVP / "backend",
        _MVP / "threezone_ai",
    ]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if "providers" in path.parts:
                continue
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
                        if alias.name.startswith(forbidden_from_prefixes):
                            offenders.append(f"{path}:{alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module in forbidden or node.module.split(".")[0] in forbidden:
                        offenders.append(f"{path}:{node.module}")
                    if node.module.startswith(forbidden_from_prefixes):
                        # jobs / product code must not import providers
                        if "jobs" in path.parts or path.name in {
                            "ai_gateway_routes.py",
                            "http_server.py",
                        }:
                            offenders.append(f"{path}:{node.module}")
    assert not offenders, f"direct AI SDK / provider imports: {offenders}"

    jobs_service = (_MVP / "threezone_ai" / "jobs" / "service.py").read_text(
        encoding="utf-8"
    )
    assert "from threezone_ai.gateway import" in jobs_service
    assert "from threezone_ai.providers" not in jobs_service
    assert "import threezone_ai.providers" not in jobs_service
    store_src = (_MVP / "threezone_ai" / "jobs" / "store.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS ai_jobs" in store_src
    assert "CREATE TABLE IF NOT EXISTS lease_records" not in store_src


def test_http_ai_jobs_routes_registered_operator():
    from backend.ai_gateway_routes import extra_routes

    routes = extra_routes()
    by_handler = {r[2]: r for r in routes}
    assert by_handler["h_ai_jobs_admit"][0] == "POST"
    assert by_handler["h_ai_jobs_admit"][3] == "operator"
    assert by_handler["h_ai_jobs_admit"][1].pattern == r"^/api/ai-jobs$"
    assert by_handler["h_ai_jobs_claim"][1].search("/api/ai-jobs/aij_abc123/claim")
    assert by_handler["h_ai_jobs_run"][1].search("/api/ai-jobs/aij_abc123/run")
    assert by_handler["h_ai_jobs_complete"][1].search("/api/ai-jobs/aij_abc123/complete")
    assert by_handler["h_ai_jobs_heartbeat"][3] == "operator"


def test_http_admit_503_when_ai_off(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    from backend import ai_gateway_routes as routes

    class _H:
        def __init__(self):
            self.status = None
            self.payload = None
            self._require_ai = routes.AiGatewayHandlers._require_ai.__get__(self, _H)
            self.h_ai_jobs_admit = routes.AiGatewayHandlers.h_ai_jobs_admit.__get__(
                self, _H
            )

        def _send_json(self, status, payload):
            self.status = status
            self.payload = payload

    h = _H()
    h.h_ai_jobs_admit({}, {"task_type": "transcription", "source_asset_id": "x"}, None)
    assert h.status == 503
    assert h.payload == {"error": "ai_disabled", "code": "ai_disabled"}


def test_terminal_job_not_reclaimable(monkeypatch):
    _enable_process(monkeypatch)
    svc = _svc()
    job = svc.admit("transcription", "asset:synthetic:done")
    svc.claim(job.job_id, "worker-a", ttl_s=60, now=1.0)
    svc.complete(job.job_id, "worker-a", result={"ok": True}, now=2.0)
    with pytest.raises(JobConflict):
        svc.claim(job.job_id, "worker-b", ttl_s=60, now=10_000.0)
