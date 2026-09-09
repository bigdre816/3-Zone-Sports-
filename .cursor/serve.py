#!/usr/bin/env python3
"""Compat entrypoint for Cloud Agent terminals (`python3 .cursor/serve.py`).

Starts Three-Zone Sports Access on :8000 when `three-zone-mvp/` is present.
Otherwise starts the Moten control plane on :8100. Never binds the leftover
Investment Tracker static file when a real product tree exists.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TZ = ROOT / "three-zone-mvp" / "run.py"
MOTEN = ROOT / "apps" / "control-plane" / "manage.py"


def main() -> None:
    if TZ.is_file():
        port = os.environ.get("PORT", "8000")
        os.environ.setdefault("TZ_ENV", "demo")
        os.environ.setdefault("TZ_HTTP_HOST", "0.0.0.0")
        os.environ.setdefault("TZ_WS_HOST", "0.0.0.0")
        os.environ.setdefault("TZ_HTTP_PORT", port)
        os.environ.setdefault(
            "TZ_ALLOWED_ORIGINS",
            f"http://127.0.0.1:{port},http://localhost:{port}",
        )
        os.chdir(TZ.parent)
        sys.argv = [
            str(TZ),
            "--http-port",
            os.environ["TZ_HTTP_PORT"],
            "--ws-port",
            os.environ.get("TZ_WS_PORT", "8765"),
            "--host",
            os.environ["TZ_HTTP_HOST"],
        ]
        runpy.run_path(str(TZ), run_name="__main__")
        return

    if MOTEN.is_file():
        os.environ.setdefault("HOST", "0.0.0.0")
        os.environ.setdefault("PORT", "8100")
        os.chdir(MOTEN.parent)
        sys.argv = [str(MOTEN), "serve"]
        runpy.run_path(str(MOTEN), run_name="__main__")
        return

    print(
        "No Three-Zone or Moten app in this checkout; not starting Investment Tracker.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
