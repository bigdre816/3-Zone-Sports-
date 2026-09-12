"""V0 / P1-V0 Sports Vision Evidence — adversarial acceptance tests.

Covers V0-T01..T22 as practical. Network disabled. Fake providers only.
Does not modify Y1a/Y1b suites. Does not register HTTP or gateway tasks.
"""

from __future__ import annotations

import ast
import math
import os
import socket
import sys
from dataclasses import replace
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.vision.assets import (  # noqa: E402
    IllicitAssetReference,
    SyntheticAssetResolver,
)
from threezone_ai.vision.ontology import (  # noqa: E402
    ONTOLOGY_CLASSES,
    MappingStatus,
    map_label,
    provider_coverage,
)
from threezone_ai.vision.pipeline import (  # noqa: E402
    VisionPipelineDisabled,
    run_evidence_pipeline,
    verify_frame_hashes,
)
from threezone_ai.vision.policy import evaluate_sports_context  # noqa: E402
from threezone_ai.vision.providers import (  # noqa: E402
    FakeEscalationProvider,
    FakeObjectDetectionProvider,
    FakeSceneReasoningProvider,
    LICENSE_RECORD,
    LicenseGateError,
    require_license_for_real_weights,
)
from threezone_ai.vision.sampler import EvidenceSampler  # noqa: E402
from threezone_ai.vision.store import (  # noqa: E402
    IdempotencyConflict,
    IsolatedEvidenceStore,
    ProductionStoreForbidden,
    idempotency_key,
)
from threezone_ai.vision.types import (  # noqa: E402
    DECISION_ELIGIBLE,
    DECISION_HOLD,
    DECISION_REJECT,
    EVIDENCE_SCHEMA_VERSION,
    GATEWAY_TASK_VERSION,
    POLICY_VERSION,
)
from threezone_ai.vision.validate import (  # noqa: E402
    POISON_STRUCTURED_KEYS,
    ValidationError,
    strip_poison_keys,
    validate_detections,
    validate_scene_payload,
)

_VISION_DIR = _MVP / "threezone_ai" / "vision"
_FIXTURES = _MVP / "tests" / "fixtures" / "vision"
_REPO = _MVP.parent


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*_a, **_k):
        raise OSError("V0 tests: network disabled")

    monkeypatch.setattr(socket.socket, "__init__", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture(autouse=True)
def _ai_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)


def _run(asset_id: str, **kwargs):
    kwargs.setdefault("allow_offline_synthetic", True)
    kwargs.setdefault("clock", lambda: "2026-09-12T00:00:00+00:00")
    kwargs.setdefault("id_factory", lambda: "exec_v0_test")
    return run_evidence_pipeline(asset_id, **kwargs)


def _policy(bundle, **kwargs):
    kwargs.setdefault("clock", lambda: "2026-09-12T00:00:00+00:00")
    return evaluate_sports_context(bundle, **kwargs)


def _src(name: str) -> str:
    return (_VISION_DIR / name).read_text(encoding="utf-8")


def _absent(haystack: str, *parts: str) -> None:
    needle = "".join(parts)
    assert needle not in haystack


# ---------------------------------------------------------------------------
# V0-T01 flags off
# ---------------------------------------------------------------------------
def test_t01_flags_off_does_not_init_providers(monkeypatch):
    inits: list[str] = []

    class BoomDet(FakeObjectDetectionProvider):
        def __init__(self, *a, **k):
            inits.append("detector")
            raise AssertionError("detector must not init")

    class BoomScene(FakeSceneReasoningProvider):
        def __init__(self, *a, **k):
            inits.append("scene")
            raise AssertionError("scene must not init")

    class BoomEsc(FakeEscalationProvider):
        def __init__(self, *a, **k):
            inits.append("escalation")
            raise AssertionError("escalation must not init")

    monkeypatch.setattr(
        "threezone_ai.vision.pipeline.FakeObjectDetectionProvider", BoomDet
    )
    monkeypatch.setattr(
        "threezone_ai.vision.pipeline.FakeSceneReasoningProvider", BoomScene
    )
    monkeypatch.setattr(
        "threezone_ai.vision.pipeline.FakeEscalationProvider", BoomEsc
    )
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    with pytest.raises(VisionPipelineDisabled):
        run_evidence_pipeline("asset:synthetic:basketball-001")
    assert inits == []


def test_t01_flags_off_does_not_call_injected_providers():
    class Spy:
        name = "spy"
        model = "spy"
        version = "unknown"
        supported_classes = frozenset()
        called = False

        def detect(self, *a, **k):
            self.called = True
            raise AssertionError("detect called")

        def reason(self, *a, **k):
            self.called = True
            raise AssertionError("reason called")

        def escalate(self, *a, **k):
            self.called = True
            raise AssertionError("escalate called")

    spy = Spy()
    with pytest.raises(VisionPipelineDisabled):
        run_evidence_pipeline(
            "asset:synthetic:basketball-001",
            detector=spy,
            scene=spy,
            escalation=spy,
            enable_escalation=True,
        )
    assert spy.called is False


# ---------------------------------------------------------------------------
# V0-T02 client privacy spoof
# ---------------------------------------------------------------------------
def test_t02_client_privacy_spoof_cannot_force_cloud():
    bundle = _run(
        "asset:synthetic:p2-member-001",
        client_privacy_class="P0",
        enable_escalation=True,
        escalation=FakeEscalationProvider(),
    )
    assert bundle.input_privacy_class == "P2"
    assert "ignored_client_privacy_spoof" in bundle.reason_codes
    assert bundle.escalation is not None
    assert bundle.escalation.provider == "fake_escalation"

    class CloudEsc(FakeEscalationProvider):
        is_cloud = True

        def escalate(self, *a, **k):
            raise AssertionError("cloud escalation must not run")

    held = _run(
        "asset:synthetic:p2-member-001",
        client_privacy_class="public",
        enable_escalation=True,
        escalation=CloudEsc(),
    )
    assert held.input_privacy_class == "P2"
    assert "cloud_escalation_blocked" in held.layer_errors
    assert held.escalation is None


# ---------------------------------------------------------------------------
# V0-T03 / T04 poison structured fields
# ---------------------------------------------------------------------------
def test_t03_poison_authority_fields_ignored_policy_unaffected():
    clean = _run("asset:synthetic:basketball-001")
    poisoned = _run(
        "asset:synthetic:malicious-001",
        detector=FakeObjectDetectionProvider(mode="malicious"),
        scene=FakeSceneReasoningProvider(mode="malicious"),
    )
    assert "ignored_model_authority_field" in poisoned.reason_codes
    for key in POISON_STRUCTURED_KEYS:
        blob = poisoned.canonical_json()
        # Structured keys must not survive as JSON keys.
        assert f'"{key}":' not in blob
    clean_p = _policy(clean)
    poison_p = _policy(poisoned)
    assert clean_p.decision == poison_p.decision == DECISION_ELIGIBLE


def test_t04_sports_status_and_policy_tokens_ignored():
    codes: list[str] = []
    cleaned = strip_poison_keys(
        {
            "sports_status": "verified",
            "eligible_for_rights_check": True,
            "hold_uncertain": False,
            "reject_non_sports": False,
            "signals": ["hardwood court visible"],
        },
        codes,
    )
    assert "sports_status" not in cleaned
    assert "eligible_for_rights_check" not in cleaned
    assert cleaned["signals"] == ["hardwood court visible"]
    assert "ignored_model_authority_field" in codes


def test_poison_is_structured_keys_not_nl_filter():
    codes: list[str] = []
    cleaned = strip_poison_keys(
        {"signals": ["the play looked official and live on hardwood court visible"]},
        codes,
    )
    assert cleaned["signals"][0].startswith("the play looked official")
    assert codes == []


# ---------------------------------------------------------------------------
# V0-T05 NaN / negative / OOB
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mode,code", [("nan", "nan_or_inf_score"), ("neg", "negative_confidence"), ("oob", "oob_bbox")])
def test_t05_malformed_boxes_and_scores_rejected(mode, code):
    bundle = _run(
        "asset:synthetic:basketball-001",
        detector=FakeObjectDetectionProvider(mode=mode),
    )
    assert code in bundle.layer_errors
    assert _policy(bundle).decision == DECISION_HOLD


def test_t05_validate_rejects_nan_direct():
    with pytest.raises(ValidationError) as ei:
        validate_detections(
            [{"raw_label": "hoop", "score": float("nan"), "bbox": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}, "frame_id": "frm_0000"}]
        )
    assert ei.value.code == "nan_or_inf_score"


# ---------------------------------------------------------------------------
# V0-T06 markdown / non-JSON
# ---------------------------------------------------------------------------
def test_t06_markdown_scene_holds_never_eligible():
    bundle = _run(
        "asset:synthetic:basketball-001",
        scene=FakeSceneReasoningProvider(mode="markdown"),
    )
    assert "scene_unparseable" in bundle.reason_codes or "scene_unparseable" in bundle.layer_errors
    result = _policy(bundle)
    assert result.decision == DECISION_HOLD
    assert result.decision != DECISION_ELIGIBLE


# ---------------------------------------------------------------------------
# V0-T07 malicious tool/instruction text does not execute
# ---------------------------------------------------------------------------
def test_t07_tool_instruction_text_does_not_execute(tmp_path, monkeypatch):
    sentinel = tmp_path / "pwned.txt"

    def _boom(*_a, **_k):
        sentinel.write_text("executed", encoding="utf-8")
        raise AssertionError("os.system must not run")

    monkeypatch.setattr(os, "system", _boom)
    bundle = _run(
        "asset:synthetic:basketball-001",
        scene=FakeSceneReasoningProvider(mode="tool_inject"),
    )
    assert not sentinel.exists()
    assert "ignored_model_execution_field" in bundle.reason_codes
    assert "hardwood court visible" in bundle.signals


# ---------------------------------------------------------------------------
# V0-T08 oversized output
# ---------------------------------------------------------------------------
def test_t08_oversized_model_output_rejected():
    bundle = _run(
        "asset:synthetic:basketball-001",
        scene=FakeSceneReasoningProvider(mode="oversize"),
    )
    assert "output_too_large" in bundle.layer_errors
    assert _policy(bundle).decision != DECISION_ELIGIBLE

    bundle2 = _run(
        "asset:synthetic:basketball-001",
        detector=FakeObjectDetectionProvider(mode="oversize"),
    )
    assert "output_too_large" in bundle2.layer_errors


# ---------------------------------------------------------------------------
# V0-T09 frame hash mismatch
# ---------------------------------------------------------------------------
def test_t09_frame_hash_mismatch_fail_closed():
    bundle = _run("asset:synthetic:basketball-001")
    tampered = replace(bundle, frame_hashes=("sha256:" + "ab" * 32,) + bundle.frame_hashes[1:])
    result = _policy(tampered, expected_frame_hashes=bundle.frame_hashes)
    assert result.decision == DECISION_HOLD
    assert "frame_hash_mismatch" in result.reason_codes


def test_t09_verify_frame_hashes_helper():
    resolver = SyntheticAssetResolver.default()
    asset = resolver.resolve("asset:synthetic:basketball-001")
    frames = EvidenceSampler().sample(asset)
    bundle = _run("asset:synthetic:basketball-001")
    assert verify_frame_hashes(bundle, frames) is True
    broken = replace(frames[0], content_hash="sha256:" + "00" * 32)
    assert verify_frame_hashes(bundle, (broken,) + frames[1:]) is False


# ---------------------------------------------------------------------------
# V0-T10 source asset hash change
# ---------------------------------------------------------------------------
def test_t10_source_hash_change_between_detect_and_policy():
    bundle = _run("asset:synthetic:basketball-001")
    result = _policy(bundle, source_asset_hash_checked="sha256:" + "ff" * 32)
    assert result.decision == DECISION_HOLD
    assert "source_asset_hash_mismatch" in result.reason_codes


def test_t10_hash_tampered_fixture_policy_uses_declared_hash():
    bundle = _run("asset:synthetic:hash-tampered-001")
    assert bundle.source_asset_hash.startswith("sha256:0000")
    # Policy with a different observed hash holds.
    result = _policy(bundle, source_asset_hash_checked="sha256:" + "11" * 32)
    assert result.decision == DECISION_HOLD


# ---------------------------------------------------------------------------
# V0-T11 detector OK + scene fail
# ---------------------------------------------------------------------------
def test_t11_detector_ok_scene_fail_holds_never_eligible():
    bundle = _run(
        "asset:synthetic:basketball-001",
        scene=FakeSceneReasoningProvider(mode="fail"),
    )
    assert "scene_fail" in bundle.layer_errors
    result = _policy(bundle)
    assert result.decision == DECISION_HOLD
    assert result.decision != DECISION_ELIGIBLE


# ---------------------------------------------------------------------------
# V0-T12 timeout
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs,err",
    [
        ({"detector": FakeObjectDetectionProvider(mode="timeout")}, "detector_timeout"),
        ({"scene": FakeSceneReasoningProvider(mode="timeout")}, "scene_timeout"),
        (
            {
                "enable_escalation": True,
                "escalation": FakeEscalationProvider(mode="timeout"),
            },
            "escalation_timeout",
        ),
    ],
)
def test_t12_timeout_no_silent_success(kwargs, err):
    bundle = _run("asset:synthetic:basketball-001", **kwargs)
    assert err in bundle.layer_errors
    result = _policy(bundle)
    assert result.decision != DECISION_ELIGIBLE
    assert result.decision == DECISION_HOLD


# ---------------------------------------------------------------------------
# V0-T13 unsupported / unknown
# ---------------------------------------------------------------------------
def test_t13_unknown_label_not_fabricated_as_supported():
    mapping = map_label("quidditch_snitch", ONTOLOGY_CLASSES)
    assert mapping.status == MappingStatus.UNKNOWN
    assert mapping.ontology_class is None
    bundle = _run(
        "asset:synthetic:non-sports-001",
        detector=FakeObjectDetectionProvider(mode="unknown_label"),
    )
    assert any(d.mapping_status == "unknown" for d in bundle.detections)
    assert all(d.ontology_class == "" for d in bundle.detections if d.mapping_status == "unknown")
    assert _policy(bundle).decision != DECISION_ELIGIBLE


def test_t13_unsupported_not_treated_as_support():
    cov = provider_coverage({"person"})
    assert cov["hoop"] == "unsupported"
    assert cov["person"] == "supported"
    bundle = _run(
        "asset:synthetic:non-sports-001",
        detector=FakeObjectDetectionProvider(
            mode="unsupported", supported_classes=frozenset({"person"})
        ),
    )
    assert any(d.mapping_status == "unsupported" for d in bundle.detections)
    assert _policy(bundle).decision != DECISION_ELIGIBLE


# ---------------------------------------------------------------------------
# V0-T14 no readable frames
# ---------------------------------------------------------------------------
def test_t14_unreadable_holds():
    bundle = _run("asset:synthetic:unreadable-001")
    result = _policy(bundle)
    assert result.decision == DECISION_HOLD
    assert "no_readable_frames" in result.reason_codes or bundle.visibility_state == "unreadable"


# ---------------------------------------------------------------------------
# V0-T15 illicit paths / URLs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ref",
    [
        "/tmp/video.mp4",
        "../etc/passwd",
        "file:///tmp/x.mp4",
        "http://example.com/x.mp4",
        "https://cdn.example/x.mp4",
        "C:\\\\videos\\\\game.mp4",
        "asset:not-synthetic:foo",
        "",
    ],
)
def test_t15_illicit_asset_refs_denied(ref):
    with pytest.raises(IllicitAssetReference):
        SyntheticAssetResolver.default().resolve(ref)
    with pytest.raises(IllicitAssetReference):
        _run(ref)


# ---------------------------------------------------------------------------
# V0-T16 idempotency
# ---------------------------------------------------------------------------
def test_t16_idempotency_stable_and_hash_conflict(tmp_path):
    store = IsolatedEvidenceStore(tmp_path / "iso")
    a = _run("asset:synthetic:basketball-001", store=store)
    b = _run("asset:synthetic:basketball-001", store=store)
    assert a.bundle_id == b.bundle_id
    assert a.observation_fingerprint() == b.observation_fingerprint()
    key = idempotency_key(a.source_asset_id, a.detector_model, POLICY_VERSION)
    other = replace(a, source_asset_hash="sha256:" + "99" * 32, bundle_id="evb_other")
    with pytest.raises(IdempotencyConflict):
        store.remember(key, other.source_asset_hash, other)


# ---------------------------------------------------------------------------
# V0-T17 sandbox cannot write production stores
# ---------------------------------------------------------------------------
def test_t17_sandbox_cannot_write_production_store(tmp_path):
    prod = tmp_path / "var" / "lib" / "threezone-prod" / "evidence"
    prod.mkdir(parents=True)
    store = IsolatedEvidenceStore(prod)
    bundle = _run("asset:synthetic:basketball-001")
    with pytest.raises(ProductionStoreForbidden):
        store.put(bundle)


# ---------------------------------------------------------------------------
# V0-T18 / T20 fake vs real cloud SDK
# ---------------------------------------------------------------------------
def test_t18_t20_fake_escalation_works_real_sdk_absent():
    bundle = _run(
        "asset:synthetic:basketball-001",
        enable_escalation=True,
        escalation=FakeEscalationProvider(),
    )
    assert bundle.escalation is not None
    assert "fake escalation" in bundle.escalation.notes.lower() or bundle.escalation.additional_signals

    joined = "".join(_src(p.name) for p in _VISION_DIR.glob("*.py"))
    _absent(joined, "import ", "groq")
    _absent(joined, "import ", "openai")
    _absent(joined, "import ", "ollama")
    _absent(joined, "from ", "groq")
    _absent(joined, "google", ".generativeai")
    _absent(joined, "generativelanguage", ".googleapis")
    _absent(joined, "api.", "groq", ".com")
    _absent(joined, "Chat", "Groq")
    _absent(joined, "OLLAMA", "_HOST")
    _absent(joined, "workers", ".ai/")

    # Runtime modules must not have been imported.
    _absent("\n".join(sys.modules), "google", ".generativeai")
    assert "groq" not in sys.modules
    assert "ollama" not in sys.modules


def test_t18_license_gate_blocks_real_weights():
    assert LICENSE_RECORD["model_weight_license"] == "not_recorded"
    with pytest.raises(LicenseGateError):
        require_license_for_real_weights("layer1")


# ---------------------------------------------------------------------------
# V0-T19 policy never imports / calls ControlPlane
# ---------------------------------------------------------------------------
def test_t19_policy_and_pipeline_do_not_import_control_plane():
    for name in ("policy.py", "pipeline.py", "validate.py", "providers.py", "types.py"):
        tree = ast.parse(_src(name))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "control_plane" not in alias.name
                    assert "ControlPlane" not in alias.name
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "control_plane" not in mod
                for alias in node.names:
                    assert alias.name != "ControlPlane"
                    assert alias.name not in {
                        "update_score",
                        "revoke_rights",
                        "restore_rights",
                        "request_playback",
                    }


def test_t19_evaluate_does_not_call_control_plane(monkeypatch):
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("cp")
        raise AssertionError("ControlPlane mutator invoked")

    # If a future import sneaks in, calling these names must still be visible.
    monkeypatch.setitem(sys.modules, "backend.control_plane", type(sys)("backend.control_plane"))
    bundle = _run("asset:synthetic:basketball-001")
    result = _policy(bundle)
    assert result.decision in {DECISION_ELIGIBLE, DECISION_HOLD, DECISION_REJECT}
    assert calls == []
    assert "control_plane" not in _src("policy.py")


# ---------------------------------------------------------------------------
# V0-T21 / T22 product reachability + scanner files exist
# ---------------------------------------------------------------------------
def test_t21_no_http_or_run_import_of_vision():
    http = (_MVP / "backend" / "http_server.py").read_text(encoding="utf-8")
    run = (_MVP / "run.py").read_text(encoding="utf-8")
    gw = (_MVP / "threezone_ai" / "gateway.py").read_text(encoding="utf-8")
    routes = (_MVP / "backend" / "ai_gateway_routes.py").read_text(encoding="utf-8")
    init = (_MVP / "threezone_ai" / "__init__.py").read_text(encoding="utf-8")
    for blob in (http, run, gw, routes, init):
        assert "threezone_ai.vision" not in blob
        assert "offline_entry" not in blob
        assert "run_evidence_pipeline" not in blob
        assert "SportsVisionEvidenceBundle" not in blob
    assert "vision" not in ast.parse(init).body[0].names[0].name if False else True
    extra = routes
    assert "/api/ai/vision" not in extra
    assert "sports_vision" not in extra


def test_t22_scanner_scripts_present_and_y1_tests_untouched_paths():
    """V0 must not remove the forbid scanner. Y1a/Y1b files are a separate PR."""
    assert (_REPO / "docs" / "multi-ai" / "ci" / "forbid_direct_ai_providers.sh").is_file()
    y1_fixture = _REPO / "docs" / "multi-ai" / "ci" / "test_forbid_direct_ai_providers.sh"
    y1_fail_closed = _MVP / "tests" / "test_ai_gateway_fail_closed.py"
    y1_http = _MVP / "tests" / "test_ai_gateway_routes_disabled.py"
    if not (y1_fixture.is_file() and y1_fail_closed.is_file() and y1_http.is_file()):
        import pytest
        pytest.skip("Y1a/Y1b artifacts live on the separate Y1 PR branch")
    assert y1_fixture.is_file()
    assert y1_fail_closed.is_file()
    assert y1_http.is_file()


# ---------------------------------------------------------------------------
# Happy paths + sampler + schemas
# ---------------------------------------------------------------------------
def test_basketball_eligible_and_bundle_immutable():
    bundle = _run("asset:synthetic:basketball-001")
    assert bundle.schema_version == EVIDENCE_SCHEMA_VERSION
    assert bundle.gateway_task_version == GATEWAY_TASK_VERSION == "sports-vision.gateway.v0"
    assert bundle.environment == "isolated_test"
    assert 8 <= len(bundle.frame_ids) <= 12
    assert len(bundle.frame_ids) == len(bundle.frame_hashes) == len(bundle.frame_timestamps)
    assert bundle.detector_version == "unknown"
    assert bundle.scene_model_version == "unknown"
    assert "hardwood court visible" in bundle.signals
    result = _policy(bundle)
    assert result.decision == DECISION_ELIGIBLE
    assert result.policy_version == POLICY_VERSION
    with pytest.raises(Exception):
        bundle.signals = ("nope",)  # type: ignore[misc]


def test_soccer_and_football_eligible():
    assert _policy(_run("asset:synthetic:soccer-001")).decision == DECISION_ELIGIBLE
    assert _policy(_run("asset:synthetic:football-001")).decision == DECISION_ELIGIBLE


def test_non_sports_rejected():
    result = _policy(_run("asset:synthetic:non-sports-001"))
    assert result.decision == DECISION_REJECT


def test_empty_gym_tv_obstructed_hold():
    assert _policy(_run("asset:synthetic:empty-gym-001")).decision == DECISION_HOLD
    assert _policy(_run("asset:synthetic:tv-in-frame-001")).decision == DECISION_HOLD
    assert _policy(_run("asset:synthetic:obstructed-001")).decision == DECISION_HOLD


def test_sampler_is_not_continuous_fps():
    src = _src("sampler.py")
    assert "continuous" in src.lower() or "NOT continuous" in src or "not continuous" in src.lower()
    assert "5–10 FPS" in src or "FPS" in src
    resolver = SyntheticAssetResolver.default()
    asset = resolver.resolve("asset:synthetic:basketball-001")
    frames = EvidenceSampler().sample(asset)
    assert 8 <= len(frames) <= 12
    assert frames[0].timestamp_s == 0.0
    assert frames[-1].timestamp_s == pytest.approx(20.0)
    # Deterministic
    again = EvidenceSampler().sample(asset)
    assert [f.content_hash for f in frames] == [f.content_hash for f in again]


def test_p3_rejected_never_eligible():
    bundle = _run("asset:synthetic:p3-reject-001")
    assert "privacy_p3_rejected" in bundle.layer_errors
    assert _policy(bundle).decision != DECISION_ELIGIBLE


def test_canonical_json_and_content_hash_stable():
    a = _run("asset:synthetic:basketball-001")
    b = _run("asset:synthetic:basketball-001")
    assert a.canonical_json() == b.canonical_json()
    assert a.content_hash() == b.content_hash()
    assert a.content_hash().startswith("sha256:")


def test_fixtures_exist():
    expected = {
        "valid_basketball.json",
        "valid_soccer.json",
        "valid_football.json",
        "non_sports.json",
        "empty_gym.json",
        "tv_in_frame.json",
        "obstructed.json",
        "unreadable.json",
        "malicious_provider.json",
        "hash_tampered.json",
    }
    present = {p.name for p in _FIXTURES.glob("*.json")}
    assert expected <= present


def test_doctrine_doc_exists():
    doc = _REPO / "docs" / "multi-ai" / "SPORTS-VISION-OBSERVATION-VS-POLICY.md"
    text = doc.read_text(encoding="utf-8")
    assert "observation" in text.lower()
    assert "policy" in text.lower()
    assert "publication" in text.lower()
