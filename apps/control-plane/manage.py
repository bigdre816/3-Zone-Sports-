#!/usr/bin/env python3
"""Phase 1 management CLI: initdb | seed | reset | serve."""

from __future__ import annotations

import os
import sys

from moten.app import create_app
from moten.config import database_url
from moten.seed import seed


def _cmd_seed() -> None:
    app = create_app()
    with app.state.session_scope() as s:
        result = seed(s)
    print(result)


def _cmd_reset() -> None:
    url = database_url()
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        if os.path.exists(path):
            os.remove(path)
            print(f"removed {path}")
    _cmd_seed()


def _cmd_serve() -> None:
    import uvicorn

    _cmd_seed()
    uvicorn.run("moten.main:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8100")))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "initdb":
        create_app()
        print("initialized")
    elif cmd == "seed":
        _cmd_seed()
    elif cmd == "reset":
        _cmd_reset()
    elif cmd == "serve":
        _cmd_serve()
    else:
        print(f"unknown command: {cmd}")
        sys.exit(2)


if __name__ == "__main__":
    main()
