"""Operator Health / Back portal dashboard — /api/ops/dashboard."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from pathlib import Path
from urllib import error, request

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from backend.config import Config  # noqa: E402
from backend.control_plane import ControlPlane, SITE_ROUTES  # noqa: E402
from backend.db import Database  # noqa: E402
from backend.live_sessions import LiveSessionService  # noqa: E402
from backend.seed import seed_if_empty  # noqa: E402

REQUIRED_TOP_KEYS = {
    "generated_at",
    "health",
    "live_readiness",
    "events",
    "rights",
    "live_sessions",
    "network",
    "media",
    "flags",
    "moten",
    "audit_recent",
    "sockets",
}

SECRET_FRAGMENTS = (
    "stream_key",
    "password",
    "token",
    "api_token",
    "signing_secret",
)


def _build_cp() -> ControlPlane:
    cfg = Config(env="development", allowed_origins=["http://127.0.0.1:8000"])
    db = Database(":memory:")
    seed_if_empty(db)
    return ControlPlane(db, cfg)


class OpsDashboardUnitTests(unittest.TestCase):
    def setUp(self):
        self.cp = _build_cp()
        self.operator = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")
        self.member = self.cp.get_user("demo-viewer")

    def test_operator_payload_has_required_keys(self):
        payload = self.cp.ops_dashboard(self.operator)
        self.assertTrue(REQUIRED_TOP_KEYS.issubset(payload.keys()), payload.keys())
        self.assertTrue(payload["health"]["ok"])
        self.assertEqual(payload["health"]["path"], "/healthz")
        self.assertIn("blockers", payload["live_readiness"])
        self.assertIn("warnings", payload["live_readiness"])
        self.assertNotIn("checks", payload["live_readiness"])

    def test_member_forbidden(self):
        from backend.control_plane import ForbiddenError

        with self.assertRaises(ForbiddenError):
            self.cp.ops_dashboard(self.member)

    def test_no_secret_looking_keys_in_json(self):
        payload = self.cp.ops_dashboard(self.owner)
        blob = json.dumps(payload)
        lowered = blob.lower()
        for frag in SECRET_FRAGMENTS:
            self.assertNotIn(frag, lowered, f"secret-looking key leaked: {frag}")

    def test_live_sessions_zero_rows(self):
        svc = LiveSessionService(self.cp)
        listed = svc.list_recent(self.operator, limit=20)
        self.assertEqual(listed["recent"], [])
        self.assertEqual(listed["by_session_state"], {})
        self.assertEqual(listed["total"], 0)
        payload = self.cp.ops_dashboard(self.operator, live_sessions=svc)
        self.assertEqual(payload["live_sessions"]["recent"], [])

    def test_site_routes_catalog_lists_dashboard(self):
        row = next(r for r in SITE_ROUTES if r["path"] == "/api/ops/dashboard")
        self.assertEqual(row["method"], "GET")
        self.assertEqual(row["tier"], "worker")


class OpsDashboardHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.http_server import make_http_server

        cfg = Config(
            env="development",
            http_host="127.0.0.1",
            http_port=0,
            allowed_origins=["http://127.0.0.1"],
        )
        db = Database(":memory:")
        seed_if_empty(db)
        cls.cp = ControlPlane(db, cfg)
        cls.httpd = make_http_server(cfg, cls.cp, media_dir=str(_MVP / "data" / "media"))
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.op_token = cls.cp.demo_login("demo-worker")["session_token"]
        cls.owner_token = cls.cp.demo_login("demo-owner")["session_token"]
        cls.member_token = cls.cp.demo_login("demo-viewer")["session_token"]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _call(self, method: str, path: str, token: str | None = None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except error.HTTPError as exc:
            payload = exc.read().decode()
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"raw": payload}
            return exc.code, parsed

    def test_operator_can_get_dashboard(self):
        status, payload = self._call("GET", "/api/ops/dashboard", token=self.op_token)
        self.assertEqual(status, 200)
        self.assertTrue(REQUIRED_TOP_KEYS.issubset(payload.keys()))

    def test_owner_can_get_dashboard(self):
        status, payload = self._call("GET", "/api/ops/dashboard", token=self.owner_token)
        self.assertEqual(status, 200)
        self.assertIn("live_sessions", payload)

    def test_member_forbidden(self):
        status, body = self._call("GET", "/api/ops/dashboard", token=self.member_token)
        self.assertEqual(status, 403)
        self.assertEqual(body.get("code"), "operator_required")

    def test_anonymous_forbidden(self):
        status, body = self._call("GET", "/api/ops/dashboard")
        self.assertIn(status, (401, 403))

    def test_http_payload_has_no_secret_keys(self):
        status, payload = self._call("GET", "/api/ops/dashboard", token=self.op_token)
        self.assertEqual(status, 200)
        blob = json.dumps(payload).lower()
        for frag in SECRET_FRAGMENTS:
            self.assertNotIn(frag, blob, f"secret-looking key leaked: {frag}")

    def test_live_sessions_list_works_with_zero_rows(self):
        status, payload = self._call("GET", "/api/ops/dashboard", token=self.op_token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["live_sessions"]["recent"], [])
        self.assertEqual(payload["live_sessions"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
