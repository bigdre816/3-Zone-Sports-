"""AI gateway flag defaults off — no network."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ROUTES = _ROOT / "three-zone-mvp" / "backend" / "ai_gateway_routes.py"
_MVP = _ROOT / "three-zone-mvp"


def _load_routes_module():
    if str(_MVP) not in sys.path:
        sys.path.insert(0, str(_MVP))
    spec = importlib.util.spec_from_file_location("ai_gateway_routes", _ROUTES)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ai_enabled_false_by_default():
    os.environ.pop("THREEZONE_AI_ENABLED", None)
    mod = _load_routes_module()
    assert mod.ai_enabled() is False


if __name__ == "__main__":
    test_ai_enabled_false_by_default()
    print("ok: ai_enabled() is False by default")
