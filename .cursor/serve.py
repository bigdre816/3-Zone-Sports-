#!/usr/bin/env python3
"""Compat entrypoint for older Cloud Agent terminals (`python3 .cursor/serve.py`).

Historically this served the leftover Investment Tracker HTML file (`System`)
on port 8000. That occupied the port Three-Zone needs for `/` and `/ops`, so
agents started a second copy on ad-hoc ports (18002) and computer-use
subagents then failed.

This shim starts the product that actually exists in the checkout:
Three-Zone on :8000 when `three-zone-mvp/` is present, otherwise the Moten
control plane on :8100. It never binds the Investment Tracker static server
when a real product tree is available.
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
        os.environ.setdefault("TZ_HTTP_HOST", "0.0.0.0")
        os.environ.setdefault("TZ_WS_HOST", "0.0.0.0")
        os.environ.setdefault("TZ_HTTP_PORT", os.environ.get("PORT", "8000"))
        os.environ.setdefault(
            "TZ_ALLOWED_ORIGINS",
            "http://127.0.0.1:8000,http://localhost:8000",
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
