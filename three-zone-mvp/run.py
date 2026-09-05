#!/usr/bin/env python3
"""Launch the Three-Zone control-plane MVP: an HTTP surface in this process and
a separate WebSocket process, sharing SQLite state.

    python run.py
    python run.py --http-port 18000 --ws-port 18765
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys

# Allow ``python run.py`` from inside the project directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import Config
from backend.control_plane import ControlPlane
from backend.db import Database
from backend.http_server import make_http_server
from backend.seed import seed_if_empty
from backend.ws_server import run_ws_process


def _media_dir(database_path: str) -> str:
    base = os.path.dirname(os.path.abspath(database_path)) or "."
    return os.path.join(base, "media")


def main() -> int:
    parser = argparse.ArgumentParser(description="Three-Zone control-plane MVP")
    parser.add_argument("--http-port", type=int, default=None)
    parser.add_argument("--ws-port", type=int, default=None)
    parser.add_argument("--host", type=str, default=None, help="bind host for both servers")
    args = parser.parse_args()

    config = Config.from_env(http_port=args.http_port, ws_port=args.ws_port,
                             http_host=args.host, ws_host=args.host)

    db = Database(config.database_path)
    if seed_if_empty(db):
        print(f"[three-zone] seeded demo inventory into {config.database_path}")
    cp = ControlPlane(db, config)
    media_dir = _media_dir(config.database_path)
    os.makedirs(media_dir, exist_ok=True)

    ws_proc = multiprocessing.Process(target=run_ws_process, args=(config,), daemon=True)
    ws_proc.start()

    httpd = make_http_server(config, cp, media_dir)
    banner = (
        "\n  Three-Zone control-plane MVP\n"
        f"  HTTP  http://{config.http_host}:{config.http_port}\n"
        f"  WS    ws://{config.ws_host}:{config.ws_port}/ws/events/<event_id>\n"
        f"  env   {config.env}   db {config.database_path}\n"
        f"  origins {', '.join(config.allowed_origins)}\n"
        "  demo accounts: demo-viewer, demo-admin\n"
    )
    print(banner, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[three-zone] shutting down", flush=True)
    finally:
        httpd.shutdown()
        if ws_proc.is_alive():
            ws_proc.terminate()
            ws_proc.join(timeout=5)
        db.close()
    return 0


if __name__ == "__main__":
    multiprocessing.set_start_method("fork", force=True)
    raise SystemExit(main())
