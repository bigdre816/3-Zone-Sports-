"""HTTP AI gateway flag defaults off — no gateway/provider dispatch.

Y1a / P1-T0: location-based path resolution (works from repo root or
three-zone-mvp/). Proves the HTTP boundary only. Does NOT claim that
threezone_ai Settings/YAML / gateway.run() defaults are fail-closed —
see forensic Addendum A / proposed Y1b.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

# Test file lives at three-zone-mvp/tests/… → parents[1] is the MVP root.
_MVP = Path(__file__).resolve().parents[1]
_ROUTES = _MVP / "backend" / "ai_gateway_routes.py"


def _load_routes_module():
    """Load ai_gateway_routes by absolute path derived from this file."""
    assert _ROUTES.is_file(), f"expected routes module at {_ROUTES}"
    if str(_MVP) not in sys.path:
        sys.path.insert(0, str(_MVP))
    # Fresh module each call so env/flag changes are visible after reload.
    name = "ai_gateway_routes_y1a_under_test"
    spec = importlib.util.spec_from_file_location(name, _ROUTES)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _clear_ai_flag() -> None:
    os.environ.pop("THREEZONE_AI_ENABLED", None)


def _set_ai_flag(value: str) -> None:
    os.environ["THREEZONE_AI_ENABLED"] = value


class _FakeHandler:
    """Minimal stand-in for HTTP mixin methods used by AiGatewayHandlers."""

    def __init__(self, mod) -> None:
        self._mod = mod
        self.status: int | None = None
        self.payload: dict[str, Any] | None = None
        # Mix in handler methods bound to this instance.
        self._require_ai = mod.AiGatewayHandlers._require_ai.__get__(self, _FakeHandler)
        self.h_ai_status = mod.AiGatewayHandlers.h_ai_status.__get__(self, _FakeHandler)
        self.h_ai_transcribe = mod.AiGatewayHandlers.h_ai_transcribe.__get__(
            self, _FakeHandler
        )

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload


def test_routes_module_path_is_single_mvp_segment():
    """Regression: never resolve three-zone-mvp/three-zone-mvp/backend/..."""
    parts = _ROUTES.parts
    # Exactly one consecutive 'three-zone-mvp' before backend
    assert "backend" in parts
    mvp_idxs = [i for i, p in enumerate(parts) if p == "three-zone-mvp"]
    assert mvp_idxs, "path should include three-zone-mvp"
    # The segment immediately after the last three-zone-mvp must be backend
    last = mvp_idxs[-1]
    assert parts[last + 1] == "backend"
    # No doubled mvp: never two consecutive three-zone-mvp
    for i in range(len(parts) - 1):
        assert not (parts[i] == "three-zone-mvp" and parts[i + 1] == "three-zone-mvp")
    assert _ROUTES.is_file()


def test_ai_enabled_false_when_unset():
    _clear_ai_flag()
    mod = _load_routes_module()
    assert mod.ai_enabled() is False


def test_ai_enabled_false_for_explicit_disabled_values():
    mod = _load_routes_module()
    for raw in ("0", "false", "FALSE", "no", "off", ""):
        _set_ai_flag(raw)
        assert mod.ai_enabled() is False, f"expected disabled for {raw!r}"


def test_disabled_status_exposes_no_gateway_details():
    _clear_ai_flag()
    mod = _load_routes_module()
    h = _FakeHandler(mod)
    h.h_ai_status(None, None, None)
    assert h.status == 200
    assert h.payload is not None
    assert h.payload.get("enabled") is False
    assert h.payload.get("gateway") is None
    # No nested summary keys that would imply config/key probing
    blob = json.dumps(h.payload)
    assert "keys_present" not in blob
    assert "ollama_base_url" not in blob
    assert "groq" not in blob.lower() or h.payload.get("gateway") is None


def test_disabled_transcribe_returns_503_without_gateway_dispatch(monkeypatch=None):
    """_require_ai runs before threezone_ai import; sentinel explodes if reached."""
    _clear_ai_flag()
    mod = _load_routes_module()

    class _Boom(Exception):
        pass

    # If disabled path ever imports/uses threezone_ai, fail loudly.
    real_import = __import__

    def _guarded_import(name, *args, **kwargs):
        if name == "threezone_ai" or name.startswith("threezone_ai."):
            raise _Boom("disabled request must not import threezone_ai")
        return real_import(name, *args, **kwargs)

    import builtins

    h = _FakeHandler(mod)
    builtins_import = builtins.__import__
    try:
        builtins.__import__ = _guarded_import  # type: ignore[assignment]
        h.h_ai_transcribe(None, {"asset_ref": "synthetic/fixture.wav"}, None)
    finally:
        builtins.__import__ = builtins_import

    assert h.status == 503
    assert h.payload == {"error": "ai_disabled", "code": "ai_disabled"}


def test_transcribe_route_registered_member_post():
    _clear_ai_flag()
    mod = _load_routes_module()
    routes = mod.extra_routes()
    matches = [
        r
        for r in routes
        if r[2] == "h_ai_transcribe"
    ]
    assert len(matches) == 1
    method, pattern, handler, auth = matches[0]
    assert method == "POST"
    assert handler == "h_ai_transcribe"
    assert auth == "member"
    assert pattern.search("/api/ai/transcribe")
    assert pattern.search("/api/ai/transcribe/") is None
    assert pattern.pattern == r"^/api/ai/transcribe$"


if __name__ == "__main__":
    test_routes_module_path_is_single_mvp_segment()
    test_ai_enabled_false_when_unset()
    test_ai_enabled_false_for_explicit_disabled_values()
    test_disabled_status_exposes_no_gateway_details()
    test_disabled_transcribe_returns_503_without_gateway_dispatch()
    test_transcribe_route_registered_member_post()
    print("ok: HTTP AI-disabled regression suite")
