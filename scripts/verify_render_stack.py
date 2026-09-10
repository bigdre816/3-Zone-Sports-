#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def request_json(method: str, url: str, *, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = resp.read().decode("utf-8")
        return resp.status, json.loads(payload) if payload else {}


def login(base: str, username: str, password: str) -> str:
    status, body = request_json("POST", f"{base}/api/auth/login", body={"username": username, "password": password})
    if status != 200 or not body.get("session_token"):
        raise SystemExit(f"login failed for {username}: {body}")
    return body["session_token"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Three-Zone + Moten deployment")
    parser.add_argument("--three-zone-base", required=True)
    parser.add_argument("--moten-base")
    parser.add_argument("--viewer-user", default="demo-viewer")
    parser.add_argument("--viewer-password", default="change-me-viewer-local")
    parser.add_argument("--owner-user", default="demo-owner")
    parser.add_argument("--owner-password", default="change-me-owner-local")
    parser.add_argument("--event-id", default="evt_mw_basketball")
    args = parser.parse_args()

    three_zone = args.three_zone_base.rstrip("/")
    owner_token = login(three_zone, args.owner_user, args.owner_password)
    viewer_token = login(three_zone, args.viewer_user, args.viewer_password)
    auth_owner = {"Authorization": "Bearer " + owner_token}
    auth_viewer = {"Authorization": "Bearer " + viewer_token}

    checks: list[tuple[str, int, dict]] = []
    checks.append(("three-zone-health",) + request_json("GET", f"{three_zone}/api/health"))
    checks.append(("member-profile",) + request_json("GET", f"{three_zone}/api/member/me", headers=auth_viewer))
    checks.append(("operator-audit",) + request_json("GET", f"{three_zone}/api/audit", headers=auth_owner))
    checks.append(("playback",) + request_json("POST", f"{three_zone}/api/events/{args.event_id}/playback-session", body={}, headers=auth_viewer))
    checks.append(("revoke",) + request_json("POST", f"{three_zone}/api/events/{args.event_id}/rights/revoke", body={"reason": "deployment-check"}, headers=auth_owner))
    checks.append(("restore",) + request_json("POST", f"{three_zone}/api/events/{args.event_id}/rights/restore", body={}, headers=auth_owner))
    checks.append(("settlement",) + request_json("GET", f"{three_zone}/api/events/{args.event_id}/settlement-manifest", headers=auth_owner))

    if args.moten_base:
        moten = args.moten_base.rstrip("/")
        checks.append(("moten-health",) + request_json("GET", f"{moten}/health"))
        checks.append(("moten-audit",) + request_json("GET", f"{moten}/audit"))
        name, status, body = ("moten-handoff",) + request_json(
            "POST",
            f"{three_zone}/api/moten/intake/event",
            body={"event_id": args.event_id},
            headers=auth_owner,
        )
        checks.append((name, status, body))
        job_id = body.get("job_id")
        if job_id:
            for _ in range(40):
                _, job = request_json("GET", f"{three_zone}/api/moten/intake/jobs/{job_id}", headers=auth_owner)
                if job.get("status") in ("delivered", "failed", "skipped"):
                    checks.append(("moten-handoff-status", 200, job))
                    break
                time.sleep(0.25)

    for name, status, body in checks:
        print(f"[{name}] {status} {json.dumps(body, sort_keys=True)}")
        if status >= 400:
            raise SystemExit(f"verification failed at {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
