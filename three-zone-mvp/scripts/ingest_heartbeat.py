#!/usr/bin/env python3
"""Encoder-side example: send a scoped heartbeat for one event and source.

The credential is created by an operator with ``POST /api/events/{id}/ingest-token``
and is scoped to exactly one event and one source (primary or backup). This
script only proves the contract; a real encoder would send the same heartbeat
from its own health loop.

Usage:
    python scripts/ingest_heartbeat.py \
        --base http://127.0.0.1:8000 \
        --event evt_mw_volleyball \
        --source primary \
        --token <ingest_token> \
        [--once] [--interval 5] [--unhealthy]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def send(base: str, event_id: str, token: str, source: str, healthy: bool) -> dict:
    url = f"{base.rstrip('/')}/api/events/{event_id}/ingest/heartbeat"
    body = json.dumps({"ingest_token": token, "source": source, "healthy": healthy}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def main() -> int:
    ap = argparse.ArgumentParser(description="Three-Zone ingest heartbeat example")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--event", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--source", default="primary", choices=["primary", "backup"])
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--unhealthy", action="store_true",
                    help="report an unhealthy feed (skips updating last-seen)")
    args = ap.parse_args()

    healthy = not args.unhealthy
    while True:
        try:
            result = send(args.base, args.event, args.token, args.source, healthy)
            print(f"heartbeat {args.source}: {result}")
        except urllib.error.HTTPError as exc:
            print(f"heartbeat rejected: {exc.code} {exc.read().decode(errors='replace')}")
        except urllib.error.URLError as exc:
            print(f"heartbeat failed: {exc}")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
