#!/usr/bin/env python3
"""Launch Three-Zone Sports Access on the Cloud Agent web port."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "three-zone-mvp")
PORT = os.environ.get("PORT", "8000")

os.chdir(APP)
sys.path.insert(0, APP)
os.environ.setdefault("TZ_ENV", "demo")
os.environ.setdefault("TZ_HTTP_HOST", "0.0.0.0")
os.environ.setdefault("TZ_HTTP_PORT", PORT)
os.environ.setdefault(
    "TZ_ALLOWED_ORIGINS",
    f"http://127.0.0.1:{PORT},http://localhost:{PORT}",
)

sys.argv = ["run.py", "--http-port", PORT, "--host", "0.0.0.0"]

from run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
