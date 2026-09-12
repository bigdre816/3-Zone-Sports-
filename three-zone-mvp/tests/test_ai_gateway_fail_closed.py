"""Y1b / P1-T1: core gateway fail-closed enablement (process gate + Settings/YAML).

Does not claim Moten intake semantics. Does not enable production AI.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from threezone_ai.config import (
    Settings,
    coerce_enablement,
    config_enabled,
    get_settings,
    load_gateway_config,
    process_ai_enabled,
    reset_settings,
)
from threezone_ai.defaults import DEFAULT_GATEWAY_CONFIG
from threezone_ai.types import AIRequest, AIResponse, TaskType


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Each test starts with process gate unset and settings cache cleared."""
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    reset_settings()
    yield
    reset_settings()
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)


def _req(**kwargs: Any) -> AIRequest:
    base = dict(
        task_type=TaskType.DESCRIPTION,
        input_text="synthetic fixture only",
        privacy_class="public",
        cost_ceiling="free_only",
        metadata={"skip_title": True},
    )
    base.update(kwargs)
    return AIRequest(**base)


def test_settings_default_false_when_env_unset():
    assert Settings().ai_enabled is False
    assert process_ai_enabled() is False
    s = Settings.from_env()
    assert s.ai_enabled is False


def test_default_yaml_and_python_defaults_disabled():
    assert DEFAULT_GATEWAY_CONFIG.get("enabled") is False
    yaml_path = Path(__file__).resolve().parents[1] / "threezone_ai" / "config.default.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    assert "\nenabled: false\n" in text or text.lstrip().startswith("enabled: false")
    # Leading comment then enabled — accept first enabled key false
    enabled_lines = [
        ln.strip() for ln in text.splitlines() if ln.strip().startswith("enabled:")
    ]
    assert enabled_lines and enabled_lines[0] == "enabled: false"
    cfg = load_gateway_config()
    assert config_enabled(cfg) is False


@pytest.mark.parametrize(
    "raw",
    [None, "", "0", "false", "FALSE", "no", "off", "maybe", "enabled", "2", "TRUEISH"],
)
def test_coerce_and_process_gate_reject_non_explicit_true(raw, monkeypatch):
    if raw is None:
        monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    else:
        monkeypatch.setenv("THREEZONE_AI_ENABLED", raw)
    assert process_ai_enabled() is False
    if raw is not None:
        assert coerce_enablement(raw, default=False) is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", "On"])
def test_process_gate_accepts_explicit_true(raw, monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", raw)
    assert process_ai_enabled() is True


def test_settings_yaml_true_cannot_bypass_unset_process_gate(monkeypatch):
    monkeypatch.delenv("THREEZONE_AI_ENABLED", raising=False)
    # Even a hand-built enabled Settings must not satisfy process gate.
    monkeypatch.setattr(
        "threezone_ai.gateway.get_settings",
        lambda reload=False: Settings(ai_enabled=True, gateway_config={"enabled": True}),
    )
    from threezone_ai.gateway import run

    resp = run(_req(), config_overlay={"enabled": True})
    assert resp.ok is False
    assert resp.provider == "no_ai"
    assert "process gate" in (resp.error or "")


def test_direct_run_unset_process_gate_returns_explicit_disabled():
    from threezone_ai.gateway import run

    resp = run(_req())
    assert isinstance(resp, AIResponse)
    assert resp.ok is False
    assert resp.provider == "no_ai"
    assert resp.degraded is True or resp.ok is False
    assert resp.error
    assert "disabled" in resp.error.lower()
    assert resp.text in (None, "")


def test_manual_enabled_settings_cannot_bypass_false_process_gate(monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "false")
    monkeypatch.setattr(
        "threezone_ai.gateway.get_settings",
        lambda reload=False: Settings(ai_enabled=True),
    )
    from threezone_ai.gateway import run

    resp = run(_req(), config_overlay={"enabled": True})
    assert resp.ok is False
    assert resp.provider == "no_ai"
    assert "process gate" in (resp.error or "")


def test_disabled_run_does_not_select_or_init_providers(monkeypatch):
    from threezone_ai import gateway as gw

    def _boom_select(*_a, **_k):
        raise AssertionError("select_providers must not run when disabled")

    def _boom_registry():
        raise AssertionError("provider registry must not initialize when disabled")

    monkeypatch.setattr(gw, "select_providers", _boom_select)
    monkeypatch.setattr(
        "threezone_ai.providers.base.get_provider_registry",
        _boom_registry,
        raising=False,
    )
    # Also patch where select_providers would import from — select itself boom is enough
    resp = gw.run(_req())
    assert resp.ok is False
    assert resp.provider == "no_ai"


def test_explicit_enablement_reaches_fake_provider_only(monkeypatch):
    """Both process + config gates on → fake provider may run; no real network."""
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")

    class FakeProvider:
        name = "fake_y1b"
        supported_tasks = {TaskType.DESCRIPTION}
        cost_band = "free"
        is_local = True

        def supports(self, task):
            return task in self.supported_tasks

        def available(self, settings):
            return True

        def run(self, request, settings):
            from threezone_ai.types import ProviderResult

            return ProviderResult(
                text="fake-ok",
                model="fake",
                version="test",
                confidence=1.0,
                metadata={"synthetic": True},
            )

    fake = FakeProvider()

    monkeypatch.setattr(
        "threezone_ai.gateway.get_settings",
        lambda reload=False: Settings(
            ai_enabled=True,
            gateway_config={"enabled": True},
        ),
    )

    def _fake_select(request, cfg=None):
        return [fake]

    monkeypatch.setattr("threezone_ai.gateway.select_providers", _fake_select)

    from threezone_ai.gateway import run

    resp = run(
        _req(),
        config_overlay={"enabled": True},
        record_lineage=False,
    )
    assert resp.ok is True
    assert resp.provider == "fake_y1b"
    assert resp.text == "fake-ok"


def test_malformed_config_enabled_stays_disabled(monkeypatch):
    monkeypatch.setenv("THREEZONE_AI_ENABLED", "true")
    monkeypatch.setattr(
        "threezone_ai.gateway.get_settings",
        lambda reload=False: Settings(ai_enabled=True),
    )
    from threezone_ai.gateway import run

    resp = run(_req(), config_overlay={"enabled": "definitely-not"})
    assert resp.ok is False
    assert resp.provider == "no_ai"
    assert "Settings/config" in (resp.error or "")


def test_config_enabled_helper_fail_closed():
    assert config_enabled({"enabled": True}) is True
    assert config_enabled({"enabled": False}) is False
    assert config_enabled({"enabled": "true"}) is True
    assert config_enabled({"enabled": "false"}) is False
    assert config_enabled({"enabled": "no"}) is False
    assert config_enabled({"enabled": 0}) is False
    assert config_enabled({"enabled": 1}) is True
    assert config_enabled({"enabled": 2}) is False
    assert config_enabled({}) is False
    assert config_enabled({"enabled": None}) is False
