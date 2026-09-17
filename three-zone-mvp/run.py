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

import dataclasses

from backend.config import Config, bind_separate_websocket
from backend.gateway import gateway_enabled, run_gateway
from backend.control_plane import ControlPlane
from backend.db import Database
from backend.http_server import make_http_server
from backend.seed import seed_if_empty
from backend.ws_server import run_ws_process


def _media_dir(database_locator: str, data_dir: str) -> str:
    if "://" in database_locator:
        base = os.path.abspath(data_dir or "data")
    else:
        base = os.path.dirname(os.path.abspath(database_locator)) or "."
    return os.path.join(base, "media")


def main() -> int:
    parser = argparse.ArgumentParser(description="Three-Zone control-plane MVP")
    parser.add_argument("--http-port", type=int, default=None)
    parser.add_argument("--ws-port", type=int, default=None)
    parser.add_argument("--host", type=str, default=None, help="bind host for both servers")
    args = parser.parse_args()

    config = Config.from_env(http_port=args.http_port, ws_port=args.ws_port,
                             http_host=args.host, ws_host=args.host)

    # Same-public-port gateway. Render exposes one port; when the gateway is
    # active it owns that port and the HTTP surface plus the WebSocket hub
    # both move to loopback behind it. See backend/gateway.py.
    use_gateway = gateway_enabled()
    gateway_proc = None
    public_host, public_port = config.http_host, config.http_port
    if use_gateway:
        internal_http = int(os.environ.get("TZ_INTERNAL_HTTP_PORT", "0")) or (public_port + 1)
        internal_ws = int(os.environ.get("TZ_WS_PORT", "8765")) or 8765
        public_origin = (
            os.environ.get("TZ_WS_PUBLIC_ORIGIN", "").strip()
            or os.environ.get("RENDER_EXTERNAL_URL", "").strip()
            or str(config.public_base_url or "").strip()
        )
        config = dataclasses.replace(
            config,
            http_host="127.0.0.1", http_port=internal_http,
            ws_host="127.0.0.1", ws_port=internal_ws,
            gateway_public_origin=public_origin,
        )

    db = Database(config.database_locator)
    if seed_if_empty(db, config.seed_passwords):
        print(f"[three-zone] seeded demo inventory into {config.database_locator}")
    cp = ControlPlane(db, config)
    media_dir = _media_dir(config.database_locator, config.data_dir)
    os.makedirs(media_dir, exist_ok=True)

    # In gateway mode the hub listens on loopback only -- it is not a second
    # public port, so Render's port scanner never sees it.
    bind_ws = True if use_gateway else bind_separate_websocket()
    ws_proc = multiprocessing.Process(
        target=run_ws_process, args=(config, bind_ws), daemon=True,
    )
    ws_proc.start()

    httpd = make_http_server(config, cp, media_dir)
    if use_gateway:
        gateway_proc = multiprocessing.Process(
            target=run_gateway,
            args=(public_host, public_port,
                  ("127.0.0.1", config.http_port), ("127.0.0.1", config.ws_port),
                  "https" if str(config.gateway_public_origin).startswith("https://") else "http"),
            daemon=True,
        )
        gateway_proc.start()
    if use_gateway:
        ws_line = (
            f"  WS    {config.public_ws_url_base() or 'disabled'}<event_id>"
            f"  (gateway :{public_port} -> http :{config.http_port}, ws :{config.ws_port})\n"
        )
    elif bind_ws:
        ws_line = f"  WS    ws://{config.ws_host}:{config.ws_port}/ws/events/<event_id>\n"
    else:
        ws_line = (
            "  WS    same-origin HTTP on this port "
            f"(separate :{config.ws_port} not bound; Render health-checks $PORT)\n"
        )
    banner = (
        "\n  Three-Zone control-plane MVP\n"
        f"  HTTP  http://{config.http_host}:{config.http_port}\n"
        f"{ws_line}"
        f"  env   {config.env}   db {config.database_locator if '://' not in config.database_locator else 'configured remote database'}\n"
        f"  origins {', '.join(config.allowed_origins)}\n"
        "  sign in with username + password (see README)\n"
        "  member site  /     control plane  /ops\n"
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
        if gateway_proc is not None and gateway_proc.is_alive():
            gateway_proc.terminate()
            gateway_proc.join(timeout=5)
        db.close()
    return 0


if __name__ == "__main__":
    multiprocessing.set_start_method("fork", force=True)
    raise SystemExit(main())
