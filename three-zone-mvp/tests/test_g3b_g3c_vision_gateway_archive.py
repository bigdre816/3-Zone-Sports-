"""G3-B sports_vision gateway task + G3-C archive source_asset_id resolver."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from threezone_ai.providers.base import get_provider_registry, reset_provider_registry
from threezone_ai.types import AIRequest, TaskType
from threezone_ai.vision.assets import (
    IllicitAssetReference,
    UnknownArchiveAsset,
    resolve_authorized_asset,
)
from threezone_ai.vision.archive_lookup import archive_lookup_from_db


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_provider_registry()
    yield
    reset_provider_registry()


def test_task_type_sports_vision_registered():
    assert TaskType.SPORTS_VISION.value == "sports_vision"
    reg = get_provider_registry()
    assert "sports_vision_offline" in reg
    assert reg["sports_vision_offline"].supports(TaskType.SPORTS_VISION)


def test_gateway_sports_vision_fail_closed_when_ai_off(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "0")
    from threezone_ai.config import reset_settings
    from threezone_ai.gateway import run

    reset_settings()
    resp = run(
        AIRequest(
            task_type=TaskType.SPORTS_VISION,
            source_asset_id="asset:synthetic:basketball-001",
        )
    )
    assert resp.ok is False
    assert resp.provider == "no_ai"
    assert "THREEZONE_AI_ENABLED" in (resp.error or "")


def test_gateway_sports_vision_runs_when_ai_on(monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    from threezone_ai.config import Settings, reset_settings
    from threezone_ai import gateway as gw

    reset_settings()
    monkeypatch.setattr(
        gw,
        "get_settings",
        lambda reload=False: Settings(ai_enabled=True, gateway_config={"enabled": True}),
    )
    resp = gw.run(
        AIRequest(
            task_type=TaskType.SPORTS_VISION,
            source_asset_id="asset:synthetic:basketball-001",
            require_human_review=True,
        ),
        config_overlay={"enabled": True},
        record_lineage=False,
    )
    assert resp.ok is True, (resp.error, resp.metadata)
    assert resp.provider == "sports_vision_offline"
    assert resp.metadata.get("decision") in {
        "eligible_for_rights_check",
        "hold_uncertain",
        "reject_non_sports",
    }
    assert resp.metadata.get("publish") is False


def test_archive_resolver_authorized():
    row = {
        "archive_id": "arc-central-wrestling",
        "status": "ARCHIVED",
        "title": "Central Wrestling — Full Game",
        "sport": "wrestling",
        "season": "2026",
        "event_id": "evt_mw_wrestling",
    }

    def lookup(aid: str):
        return row if aid == "arc-central-wrestling" else None

    asset = resolve_authorized_asset(
        "asset:archive:arc-central-wrestling",
        archive_lookup=lookup,
    )
    assert asset.source_asset_id == "asset:archive:arc-central-wrestling"
    assert asset.environment == "sandbox"
    assert asset.input_privacy_class == "P1"
    assert len(asset.frame_descriptors) >= 8


def test_archive_resolver_unknown():
    with pytest.raises(UnknownArchiveAsset):
        resolve_authorized_asset(
            "asset:archive:does-not-exist",
            archive_lookup=lambda _aid: None,
        )


def test_archive_resolver_rejects_paths_and_urls():
    with pytest.raises(IllicitAssetReference):
        resolve_authorized_asset("/etc/passwd", archive_lookup=lambda _a: None)
    with pytest.raises(IllicitAssetReference):
        resolve_authorized_asset("https://evil.example/x", archive_lookup=lambda _a: None)
    with pytest.raises(IllicitAssetReference):
        resolve_authorized_asset("asset:archive:../etc/passwd", archive_lookup=lambda _a: None)


def test_pipeline_with_archive_lookup_and_ai_flag(monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    from threezone_ai.config import reset_settings
    from threezone_ai.vision.pipeline import run_evidence_pipeline
    from threezone_ai.vision.policy import evaluate_sports_context

    reset_settings()
    row = {
        "archive_id": "arc-central-wrestling",
        "status": "ARCHIVED",
        "title": "Central Wrestling — Full Game",
        "sport": "wrestling",
        "event_id": "evt_mw_wrestling",
    }
    bundle = run_evidence_pipeline(
        "asset:archive:arc-central-wrestling",
        allow_offline_synthetic=False,
        archive_lookup=lambda aid: row if aid == "arc-central-wrestling" else None,
    )
    policy = evaluate_sports_context(bundle)
    assert bundle.environment == "sandbox"
    assert policy.decision in {
        "eligible_for_rights_check",
        "hold_uncertain",
        "reject_non_sports",
    }


def test_gateway_task_version_registered():
    from threezone_ai.vision.types import GATEWAY_TASK_VERSION

    assert GATEWAY_TASK_VERSION == "sports-vision.gateway.v0"


def test_config_lists_sports_vision_task():
    from threezone_ai.config import load_gateway_config

    cfg = load_gateway_config()
    assert "sports_vision" in (cfg.get("tasks") or {})
    order = cfg["tasks"]["sports_vision"]["default_order"]
    assert order == ["sports_vision_offline"]
