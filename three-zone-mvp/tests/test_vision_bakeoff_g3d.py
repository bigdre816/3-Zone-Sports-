"""G3-D / V1-bakeoff — ObjectDetectionProvider metrics harness + license gate."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.vision.bakeoff import (  # noqa: E402
    BakeoffCandidate,
    BakeoffReport,
    HighRecallStubDetector,
    PreciseStubDetector,
    apply_license_gate,
    default_bakeoff_corpus,
    default_ci_candidates,
    evaluate_candidate,
    run_bakeoff,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*_a, **_k):
        raise OSError("G3-D tests: network disabled")

    monkeypatch.setattr(socket.socket, "__init__", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


REQUIRED_METRIC_FIELDS = frozenset(
    {
        "candidate_id",
        "class_hits",
        "class_expected",
        "recall",
        "false_positives",
        "obstruction_behavior_flag",
        "latency_ms",
        "memory_estimate_mb",
        "license_status",
        "offline_capable",
        "verdict",
        "gate_reason",
    }
)


def test_runs_bakeoff_on_fake_corpus():
    report = run_bakeoff()
    assert isinstance(report, BakeoffReport)
    assert report.schema_version.startswith("threezone.vision.bakeoff")
    assert len(report.scenarios) >= 4
    assert len(report.candidates) >= 2
    # Corpus is synthetic / offline — basketball etc. present
    assert "basketball" in report.scenarios
    assert "non_sports" in report.scenarios
    # JSON-serializable
    payload = report.to_dict()
    json.dumps(payload)
    assert payload["offline_required"] is True


def test_unlicensed_candidate_not_green():
    cand = BakeoffCandidate(
        candidate_id="unlicensed_precise",
        provider=PreciseStubDetector(name="unlicensed_precise"),
        license_status="unlicensed",
        offline_capable=True,
        latency_ms_estimate=5.0,
        memory_estimate_mb=32.0,
    )
    metrics = evaluate_candidate(cand, default_bakeoff_corpus(), offline_required=True)
    assert metrics.verdict == "NOT_GREEN"
    assert metrics.gate_reason is not None
    assert "unlicensed" in metrics.gate_reason


def test_unknown_license_not_green():
    cand = BakeoffCandidate(
        candidate_id="unknown_high_recall",
        provider=HighRecallStubDetector(name="unknown_high_recall"),
        license_status="unknown",
        offline_capable=True,
        latency_ms_estimate=5.0,
        memory_estimate_mb=32.0,
    )
    metrics = evaluate_candidate(cand, default_bakeoff_corpus(), offline_required=True)
    assert metrics.verdict == "NOT_GREEN"
    assert metrics.gate_reason is not None
    assert "unknown" in metrics.gate_reason


def test_report_includes_metrics_fields():
    report = run_bakeoff(candidates=default_ci_candidates()[:2])
    for cand in report.candidates:
        data = cand.to_dict()
        missing = REQUIRED_METRIC_FIELDS - set(data)
        assert not missing, f"missing fields: {missing}"
        assert isinstance(data["recall"], float)
        assert isinstance(data["false_positives"], int)
        assert isinstance(data["obstruction_behavior_flag"], bool)
        assert isinstance(data["latency_ms"], (int, float))
        assert isinstance(data["memory_estimate_mb"], (int, float))
        assert data["license_status"] in {
            "permissive",
            "restricted",
            "unknown",
            "unlicensed",
        }


def test_no_network_no_weight_download_in_module_source():
    src = (_MVP / "threezone_ai" / "vision" / "bakeoff.py").read_text(encoding="utf-8")
    for needle in (
        "torch.hub",
        "ultralytics",
        "roboflow",
        "wget",
        "requests.get",
        "urllib.request",
        "huggingface",
        "download_weights",
    ):
        assert needle not in src


def test_license_gate_offline_required():
    verdict, reason = apply_license_gate(
        license_status="permissive",
        offline_capable=False,
        offline_required=True,
    )
    assert verdict == "NOT_GREEN"
    assert reason and "offline" in reason

    verdict_ok, reason_ok = apply_license_gate(
        license_status="permissive",
        offline_capable=True,
        offline_required=True,
    )
    assert verdict_ok == "GREEN"
    assert reason_ok is None


def test_permissive_offline_stub_can_green():
    cand = BakeoffCandidate(
        candidate_id="permissive_precise",
        provider=PreciseStubDetector(name="permissive_precise"),
        license_status="permissive",
        offline_capable=True,
        latency_ms_estimate=5.0,
        memory_estimate_mb=32.0,
    )
    metrics = evaluate_candidate(cand, default_bakeoff_corpus(), offline_required=True)
    assert metrics.verdict == "GREEN"
    assert metrics.gate_reason is None


def test_default_named_stubs_are_not_green_by_brand():
    report = run_bakeoff()
    by_id = {c.candidate_id: c for c in report.candidates}
    assert by_id["stub_yolo_like"].verdict == "NOT_GREEN"
    assert by_id["stub_rfdetr_like"].verdict == "NOT_GREEN"


def test_bakeoff_does_not_mention_prod_detector_switch_in_notes():
    report = run_bakeoff()
    joined = " ".join(report.notes).lower()
    assert "does not auto-switch" in joined or "not auto-switch" in joined
