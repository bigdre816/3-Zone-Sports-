"""V0b — operator sports-check API (read-only, synthetic only)."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from urllib import error, request

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from backend.config import Config  # noqa: E402
from backend.control_plane import SITE_ROUTES, ControlPlane  # noqa: E402
from backend.db import Database  # noqa: E402
from backend.seed import seed_if_empty  # noqa: E402
from backend.sports_check import list_synthetic_assets, run_sports_check  # noqa: E402


class SportsCheckUnitTests(unittest.TestCase):
    def setUp(self):
        cfg = Config(env="development", allowed_origins=["http://127.0.0.1:8000"])
        db = Database(":memory:")
        seed_if_empty(db)
        self.cp = ControlPlane(db, cfg)
        self.operator = self.cp.get_user("demo-worker")
        self.member = self.cp.get_user("demo-viewer")

    def test_list_assets_operator(self):
        payload = list_synthetic_assets(self.cp, self.operator)
        self.assertFalse(payload["publish"])
        self.assertGreaterEqual(len(payload["assets"]), 1)
        self.assertTrue(
            any(a["source_asset_id"] == "asset:synthetic:basketball-001" for a in payload["assets"])
        )

    def test_list_assets_member_forbidden(self):
        from backend.control_plane import ForbiddenError

        with self.assertRaises(ForbiddenError):
            list_synthetic_assets(self.cp, self.member)

    def test_run_basketball_returns_policy_not_publish(self):
        payload = run_sports_check(
            self.cp,
            self.operator,
            {"source_asset_id": "asset:synthetic:basketball-001"},
        )
        self.assertFalse(payload["publish"])
        self.assertFalse(payload["treasure_release"])
        self.assertTrue(payload["allow_offline_synthetic"])
        self.assertIn(payload["policy"]["decision"], {
            "eligible_for_rights_check",
            "hold_uncertain",
            "reject_non_sports",
        })
        self.assertEqual(payload["bundle"]["source_asset_id"], "asset:synthetic:basketball-001")

    def test_illicit_path_rejected(self):
        from backend.control_plane import ValidationError

        with self.assertRaises(ValidationError):
            run_sports_check(self.cp, self.operator, {"source_asset_id": "/etc/passwd"})

    def test_site_routes_catalog(self):
        paths = {r["path"] for r in SITE_ROUTES}
        self.assertIn("/api/ops/sports-check", paths)
        self.assertIn("/api/ops/sports-check/assets", paths)


class SportsCheckHttpTests(unittest.TestCase):
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
        cls.member_token = cls.cp.demo_login("demo-viewer")["session_token"]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _call(self, method: str, path: str, token: str | None = None, body: dict | None = None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body).encode()
        req = request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            headers=headers,
            data=data,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())
        except error.HTTPError as exc:
            payload = exc.read().decode()
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"raw": payload}
            return exc.code, parsed

    def test_http_operator_run(self):
        status, payload = self._call(
            "POST",
            "/api/ops/sports-check",
            token=self.op_token,
            body={"source_asset_id": "asset:synthetic:non-sports-001"},
        )
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["publish"])
        self.assertIn("policy", payload)
        self.assertIn("bundle", payload)

    def test_http_member_forbidden(self):
        status, body = self._call(
            "POST",
            "/api/ops/sports-check",
            token=self.member_token,
            body={"source_asset_id": "asset:synthetic:basketball-001"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("code"), "operator_required")

    def test_ops_html_has_pane(self):
        html = (_MVP / "backend" / "static" / "ops.html").read_text(encoding="utf-8")
        self.assertIn('data-pane="sports-check"', html)
        self.assertIn("/api/ops/sports-check", (_MVP / "backend" / "static" / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
