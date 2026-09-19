#!/usr/bin/env python3
"""Launch the Three-Zone control-plane MVP.

One public port: HTTP is served on loopback and spliced through an asyncio
gateway that also completes ``/ws/*`` against the in-process Hub.

    python run.py
    python run.py --http-port 18000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading

# Allow ``python run.py`` from inside the project directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.city_http import install_city_http
from backend.config import Config
from backend.control_plane import ControlPlane
from backend.db import Database
from backend.gateway import run_gateway
from backend.http_server import _Handler, make_http_server
from backend.portal import PortalService
from backend.seed import seed_if_empty
from backend.ws_server import Hub


def _media_dir(database_locator: str, data_dir: str) -> str:
    if "://" in database_locator:
        base = os.path.abspath(data_dir or "data")
    else:
        base = os.path.dirname(os.path.abspath(database_locator)) or "."
    return os.path.join(base, "media")


def main() -> int:
    parser = argparse.ArgumentParser(description="Three-Zone control-plane MVP")
    parser.add_argument("--http-port", type=int, default=None)
    parser.add_argument("--ws-port", type=int, default=None, help="ignored; sockets share the HTTP port")
    parser.add_argument("--host", type=str, default=None, help="bind host for the public gateway")
    args = parser.parse_args()

    config = Config.from_env(http_port=args.http_port, ws_port=args.ws_port,
                             http_host=args.host, ws_host=args.host)

    db = Database(config.database_locator)
    if seed_if_empty(db, config.seed_passwords):
        print(f"[three-zone] seeded demo inventory into {config.database_locator}")
    cp = ControlPlane(db, config)
    media_dir = _media_dir(config.database_locator, config.data_dir)
    os.makedirs(media_dir, exist_ok=True)

    # Milestone A: attach City/Getting There routes to the established handler.
    # The routes keep the existing member/operator auth classes; no parallel
    # session system or native-navigation claim is introduced here.
    install_city_http(_Handler)

    internal_port = int(os.environ.get("TZ_HTTP_INTERNAL_PORT") or "0")
    httpd = make_http_server(config, cp, media_dir, bind_host="127.0.0.1", bind_port=internal_port)
    loopback_port = httpd.server_address[1]
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()

    hub = Hub(cp, PortalService(cp))
    ws_line = f"  WS    same-origin /ws/events/<event_id> on this port (gateway)\n"
    banner = (
        "\n  Three-Zone control-plane MVP\n"
        f"  HTTP  http://{config.http_host}:{config.http_port}\n"
        f"{ws_line}"
        f"  env   {config.env}   db {config.database_locator if '://' not in config.database_locator else 'configured remote database'}\n"
        f"  origins {', '.join(config.allowed_origins)}\n"
        "  sign in with username + password (see README)\n"
        "  member site  /     city /city     control plane /ops\n"
    )
    print(banner, flush=True)
    try:
        asyncio.run(run_gateway(config, hub, loopback_port))
    except KeyboardInterrupt:
        print("\n[three-zone] shutting down", flush=True)
    finally:
        httpd.shutdown()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
