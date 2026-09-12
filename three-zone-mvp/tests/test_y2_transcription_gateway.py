"""Y2 — typed transcription gateway task (fake/offline provider)."""

from __future__ import annotations

import ast
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.providers.base import get_provider_registry, reset_provider_registry
from threezone_ai.providers.transcription_offline import (
    GATEWAY_TASK_VERSION,
    SEGMENT_SCHEMA_VERSION,
)
from threezone_ai.types import AIRequest, TaskType


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_provider_registry()
    yield
    reset_provider_registry()


def test_task_type_transcription_registered():
    assert TaskType.TRANSCRIPTION.value == "transcription"
    reg = get_provider_registry()
    assert "transcription_offline" in reg
    assert reg["transcription_offline"].supports(TaskType.TRANSCRIPTION)
    # Distinct from free-form caption
    assert not reg["transcription_offline"].supports(TaskType.CAPTION)


def test_gateway_transcription_fail_closed_when_ai_off(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "0")
    from threezone_ai.config import reset_settings
    from threezone_ai.gateway import run

    reset_settings()
    resp = run(
        AIRequest(
            task_type=TaskType.TRANSCRIPTION,
            source_asset_id="asset:synthetic:transcription-001",
        )
    )
    assert resp.ok is False
    assert resp.provider == "no_ai"
    assert "THREEZONE_AI_ENABLED" in (resp.error or "")


def test_gateway_transcription_runs_when_ai_on(monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    from threezone_ai.config import Settings, reset_settings
    from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG
    from threezone_ai import gateway as gw

    reset_settings()
    cfg = deepcopy(DEFAULT_GATEWAY_CONFIG)
    cfg["enabled"] = True
    monkeypatch.setattr(
        gw,
        "get_settings",
        lambda reload=False: Settings(ai_enabled=True, gateway_config=cfg),
    )
    resp = gw.run(
        AIRequest(
            task_type=TaskType.TRANSCRIPTION,
            source_asset_id="asset:synthetic:basketball-001",
            require_human_review=True,
        ),
        config_overlay={"enabled": True},
        record_lineage=False,
    )
    assert resp.ok is True, (resp.error, resp.metadata)
    assert resp.provider == "transcription_offline"
    assert resp.version == GATEWAY_TASK_VERSION
    assert resp.human_review_required is True
    assert resp.metadata.get("publish") is False
    assert resp.metadata.get("schema_version") == SEGMENT_SCHEMA_VERSION


def test_transcription_output_shape_stable(monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    from threezone_ai.config import Settings, reset_settings
    from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG
    from threezone_ai import gateway as gw

    reset_settings()
    cfg = deepcopy(DEFAULT_GATEWAY_CONFIG)
    cfg["enabled"] = True
    monkeypatch.setattr(
        gw,
        "get_settings",
        lambda reload=False: Settings(ai_enabled=True, gateway_config=cfg),
    )
    resp = gw.run(
        AIRequest(
            task_type=TaskType.TRANSCRIPTION,
            source_asset_id="asset:synthetic:shape-check",
        ),
        config_overlay={"enabled": True},
        record_lineage=False,
    )
    assert resp.ok is True
    assert isinstance(resp.segments, list) and len(resp.segments) >= 1
    for seg in resp.segments:
        assert set(seg.keys()) >= {"start", "end", "text"}
        assert isinstance(seg["start"], (int, float))
        assert isinstance(seg["end"], (int, float))
        assert isinstance(seg["text"], str)
        assert seg["end"] >= seg["start"]
        # speaker optional but present in fake schema (may be None)
        assert "speaker" in seg

    payload = json.loads(resp.text or "{}")
    assert payload["schema_version"] == SEGMENT_SCHEMA_VERSION
    assert payload["segments"] == resp.segments
    assert payload.get("publish") is False
    assert payload.get("treasure_release") is False


def test_gateway_task_version_registered():
    assert GATEWAY_TASK_VERSION == "transcription.gateway.v0"


def test_config_lists_transcription_task():
    from threezone_ai.config import load_gateway_config
    from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG

    cfg = load_gateway_config()
    assert "transcription" in (cfg.get("tasks") or {})
    assert cfg["tasks"]["transcription"]["default_order"] == ["transcription_offline"]
    assert cfg["tasks"]["transcription"]["human_review_default"] is True
    assert DEFAULT_GATEWAY_CONFIG["tasks"]["transcription"]["human_review_default"] is True
    assert "transcription_offline" in DEFAULT_GATEWAY_CONFIG["providers"]
    for tier in ("free_only", "low", "any"):
        assert "transcription_offline" in DEFAULT_GATEWAY_CONFIG["cost_tiers"][tier]
        assert "transcription_offline" in cfg["cost_tiers"][tier]


def test_product_code_does_not_import_ai_sdks_directly():
    """Static check: backend/ + non-provider threezone_ai must not import cloud SDKs."""
    forbidden = {
        "groq",
        "openai",
        "google.generativeai",
        "ollama",
        "faster_whisper",
    }
    roots = [
        _MVP / "backend",
        _MVP / "threezone_ai",
    ]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if "providers" in path.parts:
                continue
            if path.name == "transcription_offline.py":
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
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module in forbidden or node.module.split(".")[0] in forbidden:
                        offenders.append(f"{path}:{node.module}")
    assert not offenders, f"direct AI SDK imports in product: {offenders}"


def test_transcription_distinct_from_caption_task_order():
    from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG

    caption_order = DEFAULT_GATEWAY_CONFIG["tasks"]["caption"]["default_order"]
    tx_order = DEFAULT_GATEWAY_CONFIG["tasks"]["transcription"]["default_order"]
    assert caption_order != tx_order
    assert "transcription_offline" not in caption_order
    assert "local_faster_whisper" not in tx_order
