#!/usr/bin/env python3
"""HTTP/WebSocket smoke: member → worker → owner on a running instance.

Proves the current site still has login, zone-constrained playback, worker
ops, sports-network feed, and the owner print/JSON inventory portal.

The servers must already be running (``python run.py``). This script does not
replace them and does not mutate application source.

Usage:
    python scripts/smoke_walkthrough.py
    python scripts/smoke_walkthrough.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import DEMO_SEED_PASSWORDS

FAILURES: list[str] = []
CHECKS: list[str] = []


def record(ok: bool, name: str, detail: str = "") -> None:
    line = f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else "")
    CHECKS.append(line)
    print(line)
    if not ok:
        FAILURES.append(name)


class Client:
    def __init__(self, base: str, origin: str, ws_base: str):
        self.base = base.rstrip("/")
        self.origin = origin
        self.ws_base = ws_base.rstrip("/") + "/"

    def req(self, method: str, path: str, body=None, token=None):
        headers = {"Origin": self.origin}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            with opener.open(request, timeout=10) as resp:
                raw = resp.read()
                payload = json.loads(raw) if raw else {}
                cookies = {c.name: c.value for c in jar}
                return resp.status, payload, dict(resp.headers), cookies
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw.decode("utf-8", "replace")}
            return exc.code, payload, dict(exc.headers), {}

    def get_text(self, path: str) -> tuple[int, str]:
        request = urllib.request.Request(self.base + path, headers={"Origin": self.origin})
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def password_login(self, username: str) -> tuple[str, dict]:
        password = DEMO_SEED_PASSWORDS[username]
        status, payload, _, _ = self.req(
            "POST", "/api/auth/login", {"username": username, "password": password}
        )
        record(status == 200 and "session_token" in payload,
               f"password login {username}", f"status={status}")
        if status != 200:
            raise SystemExit(f"cannot login {username}: {payload}")
        user = payload["user"]
        record(user["user_id"] == username, f"{username} identity", user.get("role"))
        expected_home = "/ops" if user["role"] in ("operator", "owner", "admin") else "/"
        record(payload.get("home") == expected_home,
               f"{username} home is {expected_home}", str(payload.get("home")))
        return payload["session_token"], user

    async def ws_snapshot(self, event_id: str, token: str):
        url = self.ws_base + event_id
        async with websockets.connect(
            url,
            origin=self.origin,
            subprotocols=["tz-session", token],
            open_timeout=5,
            close_timeout=2,
        ) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            await ws.send(json.dumps({"type": "ping"}))
            pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            return msg, pong


def run(client: Client) -> int:
    print("=== HTTP health ===")
    status, payload, _, _ = client.req("GET", "/api/health")
    record(status == 200 and payload.get("status") == "ok", "GET /api/health", str(payload))

    status, cfg, _, _ = client.req("GET", "/api/config")
    record(status == 200 and "ws_url_base" in cfg, "GET /api/config", cfg.get("ws_url_base"))
    record(cfg.get("register_enabled") is True, "config allows member registration")
    blob = json.dumps(cfg)
    record("token_secret" not in blob and "media_service" not in blob,
           "public config has no secrets")

    status, demo, _, _ = client.req("POST", "/api/auth/demo-login", {"account": "demo-viewer"})
    record(status == 200 and demo.get("session_token"),
           "legacy demo-login still issues a session")

    print("\n=== MEMBER (demo-viewer) ===")
    member_token, member = client.password_login("demo-viewer")
    record(member["role"] == "viewer", "member role is viewer", member["role"])

    status, me, _, _ = client.req("GET", "/api/me", token=member_token)
    record(status == 200 and me["user"]["user_id"] == "demo-viewer", "member GET /api/me")

    status, events, _, _ = client.req("GET", "/api/events", token=member_token)
    titles = [e["title"] for e in events.get("events", [])]
    zones = {e["zone"] for e in events.get("events", [])}
    record(status == 200, "member catalog", f"{len(titles)} events")
    record("Lincoln Freshman Basketball" in titles, "member sees Lincoln Freshman Basketball")
    record(zones <= {"midwest"}, "member catalog is midwest-only", str(zones))
    record("Harbor Baseball (Replay)" not in titles, "member does not see west replay")

    status, feed, _, _ = client.req("GET", "/api/network/feed", token=member_token)
    record(status == 200 and "items" in feed, "member sports-network feed",
           f"status={status} keys={list(feed)[:8]}")

    status, pb, headers, cookies = client.req(
        "POST", "/api/events/evt_mw_basketball/playback-session", token=member_token
    )
    record(status == 200 and pb.get("allow") is True and pb.get("mode") == "live",
           "member live lease for Lincoln Freshman Basketball",
           f"status={status} mode={pb.get('mode')}")
    set_cookie = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
    record("tz_lease_evt_mw_basketball" in set_cookie, "lease delivered as Set-Cookie")
    record("lease_token" not in pb, "lease token not in JSON body")

    cookie_val = cookies.get("tz_lease_evt_mw_basketball") or ""
    if not cookie_val:
        for part in set_cookie.split(";"):
            part = part.strip()
            if part.startswith("tz_lease_evt_mw_basketball="):
                cookie_val = part.split("=", 1)[1].strip()
                break
    media_req = urllib.request.Request(
        client.base + "/demo/media/evt_mw_basketball.mp4",
        headers={"Cookie": f"tz_lease_evt_mw_basketball={cookie_val}"},
    )
    try:
        with urllib.request.urlopen(media_req, timeout=15) as resp:
            media_status = resp.status
            n = len(resp.read(64))
    except urllib.error.HTTPError as exc:
        media_status = exc.code
        n = 0
    record(media_status == 200 and n > 0, "member media playback bytes",
           f"status={media_status} n={n}")

    status, denied, _, _ = client.req(
        "POST", "/api/events", {"title": "nope", "zone": "midwest"}, token=member_token
    )
    record(status == 403 and denied.get("code") == "operator_required",
           "member cannot create event", str(denied))

    status, denied, _, _ = client.req("GET", "/api/owner/inventory", token=member_token)
    record(status == 403 and denied.get("code") == "owner_required",
           "member cannot open owner inventory", str(denied))

    print("\n=== MEMBER websocket ===")
    snap, pong = asyncio.run(client.ws_snapshot("evt_mw_basketball", member_token))
    record(snap.get("type") == "event.state", "member WS event.state", snap.get("type"))
    record((snap.get("snapshot") or {}).get("title") == "Lincoln Freshman Basketball",
           "member WS snapshot title", (snap.get("snapshot") or {}).get("title"))
    record(pong.get("type") == "pong", "member WS ping/pong", str(pong.get("type")))

    print("\n=== WORKER (demo-worker) ===")
    worker_token, worker = client.password_login("demo-worker")
    record(worker["role"] == "operator", "worker role is operator", worker["role"])

    status, events, _, _ = client.req("GET", "/api/events", token=worker_token)
    all_titles = [e["title"] for e in events.get("events", [])]
    record(status == 200 and len(all_titles) >= 8, "worker sees all-zone catalog",
           f"{len(all_titles)} events")

    status, created, _, _ = client.req(
        "POST", "/api/events",
        {"title": "Smoke Test Event", "zone": "midwest", "category": "general",
         "production_mode": "single_camera"},
        token=worker_token,
    )
    record(status == 201, "worker create event", str(created.get("event", {}).get("event_id")))
    new_id = created.get("event", {}).get("event_id")

    status, trans, _, _ = client.req(
        "POST", f"/api/events/{new_id}/transition", {"target": "gray"}, token=worker_token
    )
    record(status == 200 and trans.get("event", {}).get("status") == "gray",
           "worker transition scheduled→gray", trans.get("event", {}).get("status"))

    status, ingest, _, _ = client.req(
        "POST", "/api/events/evt_mw_volleyball/ingest-token",
        {"source": "primary"}, token=worker_token,
    )
    record(status == 201 and ingest.get("ingest_token"),
           "worker issue ingest token", ingest.get("source"))

    status, hb, _, _ = client.req(
        "POST", "/api/events/evt_mw_volleyball/ingest/heartbeat",
        {"ingest_token": ingest["ingest_token"], "source": "primary", "healthy": True},
    )
    record(status == 200, "worker ingest heartbeat", str(hb)[:160])

    status, _, _, _ = client.req(
        "POST", "/api/events/evt_mw_volleyball/score",
        {"scoreboard": {"home": 2, "away": 1, "period": "Set 3", "clock": "20-18"}},
        token=worker_token,
    )
    record(status == 200, "worker scoreboard update")

    status, audit, _, _ = client.req("GET", "/api/audit", token=worker_token)
    record(status == 200 and isinstance(audit.get("audit"), list) and audit["audit"],
           "worker can read audit", f"{len(audit.get('audit', []))} entries")

    status, denied, _, _ = client.req("GET", "/api/owner/inventory", token=worker_token)
    record(status == 403 and denied.get("code") == "owner_required",
           "worker cannot open owner inventory", str(denied))

    status, _, _, _ = client.req(
        "POST", "/api/events/evt_mw_soccer/rights/revoke",
        {"reason": "smoke-test dispute"}, token=worker_token,
    )
    record(status == 200, "worker revoke rights on live event")

    status, restored, _, _ = client.req(
        "POST", "/api/events/evt_mw_soccer/rights/restore", token=worker_token
    )
    record(status == 200 and restored.get("event", {}).get("rights", {}).get("version", 0) >= 2,
           "worker restore rights new version",
           str(restored.get("event", {}).get("rights", {}).get("version")))

    print("\n=== OWNER (demo-owner) ===")
    owner_token, owner = client.password_login("demo-owner")
    record(owner["role"] == "owner", "owner role is owner", owner["role"])

    status, inv, _, _ = client.req("GET", "/api/owner/inventory", token=owner_token)
    record(status == 200, "owner GET /api/owner/inventory")
    if status != 200:
        print(inv)
        return 1

    totals = inv.get("totals", {})
    record(totals.get("users", 0) >= 3, "inventory users", str(totals))
    record(totals.get("events", 0) >= 8, "inventory events", str(totals.get("events")))
    record(totals.get("rights_versions", 0) >= 8, "inventory rights versions")
    record(totals.get("audit_entries", 0) >= 1, "inventory audit entries")

    tiers = {t["tier"] for t in inv.get("tiers", [])}
    record(tiers == {"member", "worker", "owner"}, "inventory tier map", str(tiers))

    routes = {(r["method"], r["path"]) for r in inv.get("routes", [])}
    record(("GET", "/api/owner/inventory") in routes, "route map includes owner inventory")
    record(("POST", "/api/auth/login") in routes, "route map includes password login")
    record(("GET", "/api/network/feed") in routes, "route map includes sports-network feed")

    users = {u["user_id"]: u["role"] for u in inv.get("users", [])}
    record(users.get("demo-viewer") == "viewer" and users.get("demo-worker") == "operator"
           and users.get("demo-owner") == "owner", "inventory users/roles", str(users))

    soccer = next((e for e in inv["events"] if e["event_id"] == "evt_mw_soccer"), None)
    record(soccer is not None, "inventory includes Prairie Soccer")
    versions = soccer["rights_versions"] if soccer else []
    record(any(v.get("revoked") for v in versions) and any(v.get("active") for v in versions),
           "inventory includes full revoked+active rights history")

    dump = json.dumps(inv)
    record("three-zone-demo-token-secret" not in dump
           and "three-zone-demo-media-service-key" not in dump
           and "change-me-viewer-local" not in dump,
           "JSON export does not contain demo secret values")

    status, analytics, _, _ = client.req("GET", "/api/analytics", token=owner_token)
    record(status == 200, "owner analytics", str(list(analytics.keys())[:8]))

    print("\n=== OWNER websocket ===")
    snap, pong = asyncio.run(client.ws_snapshot("evt_mw_basketball", owner_token))
    record(snap.get("type") == "event.state", "owner WS event.state")
    record(pong.get("type") == "pong", "owner WS ping/pong")

    print("\n=== UI shell (current site, not the old combined page) ===")
    st, html = client.get_text("/")
    record(st == 200 and "Watch it. Save it. Clip it. Share it." in html,
           "member site still serves the sports-network home")
    record("login-form" in html and "register-form" in html,
           "member site still has sign-in and create-account")

    st, ops = client.get_text("/ops")
    record(st == 200 and "Control plane" in ops, "ops console is still on /ops")
    record("Print everything" in ops and "Download JSON export" in ops,
           "owner print/JSON export controls are on /ops")
    record("Network review" in ops, "ops console still has network review")

    st, js = client.get_text("/app.js")
    record(st == 200 and "ownerPrint" in js and "ownerExport" in js and "window.print" in js,
           "app.js still implements print and JSON export")

    print("\n======== SUMMARY ========")
    print(f"{len(CHECKS) - len(FAILURES)} passed, {len(FAILURES)} failed, {len(CHECKS)} total")
    if FAILURES:
        print("FAILED:", ", ".join(FAILURES))
        return 1
    print("ALL SMOKE CHECKS PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Three-Zone member/worker/owner smoke")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--ws-base", default="ws://127.0.0.1:8765/ws/events")
    args = parser.parse_args()
    origin = args.base.rstrip("/")
    client = Client(args.base, origin, args.ws_base)
    return run(client)


if __name__ == "__main__":
    sys.exit(main())
