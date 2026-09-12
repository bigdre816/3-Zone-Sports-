"""L1B — private live capture session tests (22 required cases).

Isolated SQLite (:memory: / temp). Network-free. No provider / AI / Moten /
XRPL / settlement / ControlPlane.transition(live) side effects.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request

_MVP = Path(__file__).resolve().parents[1]
if str(_MVP) not in sys.path:
    sys.path.insert(0, str(_MVP))

from backend.config import (  # noqa: E402
    Config,
    live_continuous_verify_enabled,
    live_publication_enabled,
    member_live_enabled,
    private_live_capture_enabled,
    sports_verify_enabled,
)
from backend.control_plane import (  # noqa: E402
    ConflictError,
    ControlPlane,
    ForbiddenError,
    NotFoundError,
)
from backend.db import Database  # noqa: E402
from backend.live_sessions import (  # noqa: E402
    DISTRIBUTION_DISABLED,
    FeatureDisabledError,
    LiveSessionService,
    PROVIDER_NAME,
    PUBLIC_STATE_LIVE_PRIVATE,
    SAFETY_NOT_EVALUATED,
    SPORTS_UNVERIFIED,
    STATE_CAPTURE_STARTING,
    STATE_FAILED,
    STATE_REQUESTED,
    STATE_STOPPED,
    STATE_STOP_REQUESTED,
    STATE_VERIFYING_PRIVATE,
)
from backend.seed import seed_if_empty  # noqa: E402


FLAG = "THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED"
FUTURE_FLAGS = (
    "THREEZONE_MEMBER_LIVE_ENABLED",
    "THREEZONE_SPORTS_VERIFY_ENABLED",
    "THREEZONE_LIVE_PUBLICATION_ENABLED",
    "THREEZONE_LIVE_CONTINUOUS_VERIFY_ENABLED",
)


def _clear_live_flags() -> None:
    os.environ.pop(FLAG, None)
    for name in FUTURE_FLAGS:
        os.environ.pop(name, None)


def _build() -> tuple[ControlPlane, LiveSessionService]:
    cfg = Config(env="development", allowed_origins=["http://127.0.0.1:8000"])
    db = Database(":memory:")
    seed_if_empty(db)
    cp = ControlPlane(db, cfg)
    return cp, LiveSessionService(cp)


class FlagFailClosedTests(unittest.TestCase):
    def tearDown(self):
        _clear_live_flags()

    def test_01_flag_unset_disabled(self):
        _clear_live_flags()
        self.assertFalse(private_live_capture_enabled())

    def test_02_flag_blank_and_false_like_disabled(self):
        for raw in ("", " ", "0", "false", "FALSE", "no", "off", "garbage", "2"):
            os.environ[FLAG] = raw
            self.assertFalse(private_live_capture_enabled(), f"expected off for {raw!r}")

    def test_03_flag_true_like_enabled(self):
        for raw in ("1", "true", "TRUE", "yes", "on"):
            os.environ[FLAG] = raw
            self.assertTrue(private_live_capture_enabled(), f"expected on for {raw!r}")

    def test_04_future_flags_default_disabled(self):
        _clear_live_flags()
        self.assertFalse(member_live_enabled())
        self.assertFalse(sports_verify_enabled())
        self.assertFalse(live_publication_enabled())
        self.assertFalse(live_continuous_verify_enabled())


class ServiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        os.environ[FLAG] = "true"
        self.cp, self.svc = _build()
        self.operator = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")
        self.member = self.cp.get_user("demo-viewer")
        self._moten_before = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM moten_outbox"
        )["c"]
        self._events_before = {
            r["event_id"]: r["status"]
            for r in self.cp.db.query("SELECT event_id, status FROM events")
        }
        self._xrpl_before = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM xrpl_publications"
        )["c"]
        self._settlements_before = self.cp.db.query_one(
            "SELECT COUNT(*) AS c FROM settlements"
        )["c"]

    def tearDown(self):
        _clear_live_flags()

    def test_05_disabled_creates_nothing(self):
        os.environ[FLAG] = "false"
        with self.assertRaises(FeatureDisabledError) as ctx:
            self.svc.start(self.operator, {"idempotency_key": "x"})
        self.assertEqual(ctx.exception.code, "private_live_capture_disabled")
        self.assertEqual(ctx.exception.status, 503)
        count = self.cp.db.query_one("SELECT COUNT(*) AS c FROM live_sessions")["c"]
        self.assertEqual(count, 0)

    def test_06_operator_and_owner_can_start(self):
        a = self.svc.start(self.operator, {"idempotency_key": "op1"})
        b = self.svc.start(self.owner, {"idempotency_key": "ow1"})
        self.assertEqual(a["session_state"], STATE_VERIFYING_PRIVATE)
        self.assertEqual(b["session_state"], STATE_VERIFYING_PRIVATE)
        self.assertTrue(a["live_session_id"].startswith("ls_"))

    def test_07_member_denied(self):
        with self.assertRaises(ForbiddenError) as ctx:
            self.svc.start(self.member, {"idempotency_key": "m1"})
        self.assertEqual(ctx.exception.code, "operator_required")

    def test_08_server_forced_truth_fields(self):
        s = self.svc.start(self.operator, {"idempotency_key": "truth"})
        self.assertEqual(s["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(s["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertEqual(s["sports_status"], SPORTS_UNVERIFIED)
        self.assertEqual(s["safety_state"], SAFETY_NOT_EVALUATED)
        self.assertEqual(s["provider_name"], PROVIDER_NAME)
        self.assertIsNone(s["provider_stream_id"])
        self.assertIsNone(s["restream_event_id"])
        self.assertFalse(s["publication"]["browser_source_published"])
        self.assertIn("not published", s["publication"]["label"].lower())

    def test_09_malicious_client_fields_ignored(self):
        s = self.svc.start(self.operator, {
            "idempotency_key": "evil",
            "sports_status": "SPORTS_VERIFIED",
            "public_state": "LIVE_PUBLIC",
            "distribution_state": "ENABLED",
            "safety_state": "SAFE",
            "provider_name": "restream",
            "provider_stream_id": "hack",
            "restream_event_id": "rst_evil",
            "rights_version": 999,
            "policy_version": "pwned",
            "session_state": "STOPPED",
            "source_asset_id": "x",
        })
        self.assertEqual(s["sports_status"], SPORTS_UNVERIFIED)
        self.assertEqual(s["public_state"], PUBLIC_STATE_LIVE_PRIVATE)
        self.assertEqual(s["distribution_state"], DISTRIBUTION_DISABLED)
        self.assertEqual(s["safety_state"], SAFETY_NOT_EVALUATED)
        self.assertEqual(s["provider_name"], PROVIDER_NAME)
        self.assertIsNone(s["provider_stream_id"])
        self.assertIsNone(s["restream_event_id"])
        self.assertNotEqual(s["rights_version"], 999)
        self.assertEqual(s["session_state"], STATE_VERIFYING_PRIVATE)
        # Prove no SPORTS_VERIFIED / LIVE_PUBLIC / PUBLICATION rows exist.
        row = self.cp.db.query_one(
            "SELECT * FROM live_sessions WHERE live_session_id=?",
            (s["live_session_id"],),
        )
        self.assertNotEqual(row["sports_status"], "SPORTS_VERIFIED")
        self.assertNotEqual(row["public_state"], "LIVE_PUBLIC")
        self.assertNotEqual(row["public_state"], "PUBLICATION_PENDING")

    def test_10_state_graph_start_lands_verifying_private(self):
        s = self.svc.start(self.operator, {"idempotency_key": "graph"})
        self.assertEqual(s["session_state"], STATE_VERIFYING_PRIVATE)
        self.assertIsNotNone(s["requested_at"])
        self.assertIsNotNone(s["capture_starting_at"])
        self.assertIsNotNone(s["verifying_private_at"])

    def test_11_stop_path_to_stopped(self):
        s = self.svc.start(self.operator, {"idempotency_key": "stop1"})
        out = self.svc.stop(self.operator, s["live_session_id"], {"reason": "done"})
        self.assertEqual(out["session_state"], STATE_STOPPED)
        self.assertEqual(out["stop_reason"], "done")
        self.assertIsNotNone(out["stop_requested_at"])
        self.assertIsNotNone(out["stopped_at"])

    def test_12_fail_from_verifying_private(self):
        s = self.svc.start(self.operator, {"idempotency_key": "fail1"})
        out = self.svc.mark_failed(self.operator, s["live_session_id"], "boom")
        self.assertEqual(out["session_state"], STATE_FAILED)
        self.assertEqual(out["failure_reason"], "boom")

    def test_13_illegal_transition_after_stopped(self):
        s = self.svc.start(self.operator, {"idempotency_key": "ill"})
        self.svc.stop(self.operator, s["live_session_id"])
        with self.assertRaises(ConflictError) as ctx:
            self.svc.mark_failed(self.operator, s["live_session_id"], "nope")
        self.assertEqual(ctx.exception.code, "illegal_live_session_transition")

    def test_14_idempotent_start_same_key(self):
        a = self.svc.start(self.operator, {
            "idempotency_key": "idem",
            "event_id": "evt_mw_basketball",
        })
        b = self.svc.start(self.operator, {
            "idempotency_key": "idem",
            "event_id": "evt_mw_basketball",
        })
        self.assertEqual(a["live_session_id"], b["live_session_id"])
        count = self.cp.db.query_one("SELECT COUNT(*) AS c FROM live_sessions")["c"]
        self.assertEqual(count, 1)

    def test_15_idempotency_conflict_different_input(self):
        self.svc.start(self.operator, {
            "idempotency_key": "clash",
            "event_id": "evt_mw_basketball",
        })
        with self.assertRaises(ConflictError) as ctx:
            self.svc.start(self.operator, {
                "idempotency_key": "clash",
                "event_id": "evt_w_football",
            })
        self.assertEqual(ctx.exception.code, "idempotency_conflict")

    def test_16_idempotent_stop(self):
        s = self.svc.start(self.operator, {"idempotency_key": "stop-idem"})
        a = self.svc.stop(self.operator, s["live_session_id"])
        b = self.svc.stop(self.operator, s["live_session_id"])
        self.assertEqual(a["session_state"], STATE_STOPPED)
        self.assertEqual(b["session_state"], STATE_STOPPED)

    def test_17_get_and_unknown_id(self):
        s = self.svc.start(self.operator, {"idempotency_key": "get1"})
        got = self.svc.get(self.operator, s["live_session_id"])
        self.assertEqual(got["live_session_id"], s["live_session_id"])
        with self.assertRaises(NotFoundError) as ctx:
            self.svc.get(self.operator, "ls_doesnotexist000")
        self.assertEqual(ctx.exception.code, "live_session_not_found")

    def test_18_event_id_validates_and_records_rights_without_lifecycle_mutation(self):
        before = self.cp.get_event_row("evt_mw_basketball")["status"]
        rights = self.cp.current_rights("evt_mw_basketball")
        s = self.svc.start(self.operator, {
            "idempotency_key": "rights",
            "event_id": "evt_mw_basketball",
        })
        self.assertEqual(s["event_id"], "evt_mw_basketball")
        self.assertEqual(s["rights_version"], int(rights["version"]))
        after = self.cp.get_event_row("evt_mw_basketball")["status"]
        self.assertEqual(before, after)
        with self.assertRaises(NotFoundError):
            self.svc.start(self.operator, {
                "idempotency_key": "bad-evt",
                "event_id": "evt_missing_zzz",
            })

    def test_19_no_truth_plane_provider_ai_moten_side_effects(self):
        s = self.svc.start(self.operator, {"idempotency_key": "sidefx"})
        self.svc.stop(self.operator, s["live_session_id"])
        # Event lifecycle unchanged.
        after_events = {
            r["event_id"]: r["status"]
            for r in self.cp.db.query("SELECT event_id, status FROM events")
        }
        self.assertEqual(self._events_before, after_events)
        # No Moten outbox rows added.
        moten_after = self.cp.db.query_one("SELECT COUNT(*) AS c FROM moten_outbox")["c"]
        self.assertEqual(moten_after, self._moten_before)
        # No XRPL / settlements.
        self.assertEqual(
            self.cp.db.query_one("SELECT COUNT(*) AS c FROM xrpl_publications")["c"],
            self._xrpl_before,
        )
        self.assertEqual(
            self.cp.db.query_one("SELECT COUNT(*) AS c FROM settlements")["c"],
            self._settlements_before,
        )
        # Audit entries exist (audit_log pattern) but actions are live_session.*.
        audits = self.cp.db.query(
            "SELECT action FROM audit WHERE event_id=?",
            (s["live_session_id"],),
        )
        actions = {a["action"] for a in audits}
        self.assertTrue(any(a.startswith("live_session.") for a in actions))
        self.assertNotIn("event.transition", actions)
        # Provider identity stays local_browser.
        row = self.cp.db.query_one(
            "SELECT provider_name, provider_stream_id, restream_event_id, "
            "distribution_state, public_state FROM live_sessions WHERE live_session_id=?",
            (s["live_session_id"],),
        )
        self.assertEqual(row["provider_name"], "local_browser")
        self.assertIsNone(row["provider_stream_id"])
        self.assertIsNone(row["restream_event_id"])
        self.assertEqual(row["distribution_state"], "DISABLED")
        self.assertEqual(row["public_state"], "LIVE_PRIVATE")

    def test_20_schema_live_sessions_table_present(self):
        cols = {
            r["name"] if isinstance(r, dict) else r[1]
            for r in self.cp.db.query("PRAGMA table_info(live_sessions)")
        }
        # sqlite Row: PRAGMA returns cid, name, type...
        if not cols or "live_session_id" not in cols:
            # Row access by index/name
            rows = self.cp.db.query("PRAGMA table_info(live_sessions)")
            cols = set()
            for r in rows:
                try:
                    cols.add(r["name"])
                except Exception:
                    cols.add(r[1])
        required = {
            "live_session_id", "actor_id", "event_id", "session_state",
            "sports_status", "public_state", "distribution_state", "safety_state",
            "provider_name", "rights_version", "policy_version", "env",
            "created_at", "updated_at",
        }
        self.assertTrue(required.issubset(cols), f"missing {required - cols}")


class HttpBoundaryTests(unittest.TestCase):
    """HTTP operator-only + disabled response + no metadata leak."""

    @classmethod
    def setUpClass(cls):
        os.environ[FLAG] = "true"
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
        # Issue tokens
        cls.op_token = cls.cp.demo_login("demo-worker")["session_token"]
        cls.member_token = cls.cp.demo_login("demo-viewer")["session_token"]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        _clear_live_flags()

    def setUp(self):
        os.environ[FLAG] = "true"

    def tearDown(self):
        os.environ[FLAG] = "true"

    def _call(self, method: str, path: str, token: str | None = None, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
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

    def test_21_http_operator_ok_member_unauth_denied_disabled_503(self):
        # Operator create OK
        status, payload = self._call(
            "POST", "/api/live-sessions",
            token=self.op_token,
            body={"idempotency_key": "http-op"},
        )
        self.assertEqual(status, 201)
        sid = payload["live_session"]["live_session_id"]
        self.assertEqual(payload["live_session"]["distribution_state"], "DISABLED")

        # Member denied — no session metadata leak beyond error code
        st, body = self._call(
            "POST", "/api/live-sessions",
            token=self.member_token,
            body={"idempotency_key": "http-mem"},
        )
        self.assertEqual(st, 403)
        self.assertEqual(body.get("code"), "operator_required")
        self.assertNotIn("live_session", body)

        # Unauth denied
        st, body = self._call("POST", "/api/live-sessions", body={"idempotency_key": "u"})
        self.assertIn(st, (401, 403))
        self.assertNotIn("live_session", body)

        # Guessed ID as member — no leak
        st, body = self._call(
            "GET", f"/api/live-sessions/{sid}",
            token=self.member_token,
        )
        self.assertEqual(st, 403)
        blob = json.dumps(body)
        self.assertNotIn(sid, blob)
        self.assertNotIn("LIVE_PRIVATE", blob)

        # Guessed nonexistent as operator → generic 404
        st, body = self._call(
            "GET", "/api/live-sessions/ls_guessedffffffff",
            token=self.op_token,
        )
        self.assertEqual(st, 404)
        self.assertEqual(body.get("code"), "live_session_not_found")

        # Flag off → 503 explicit disabled (operator)
        os.environ[FLAG] = "false"
        st, body = self._call(
            "POST", "/api/live-sessions",
            token=self.op_token,
            body={"idempotency_key": "http-off"},
        )
        self.assertEqual(st, 503)
        self.assertEqual(body.get("code"), "private_live_capture_disabled")
        os.environ[FLAG] = "true"

        # Stop works
        st, body = self._call(
            "POST", f"/api/live-sessions/{sid}/stop",
            token=self.op_token,
            body={"reason": "http_stop"},
        )
        self.assertEqual(st, 200)
        self.assertEqual(body["live_session"]["session_state"], STATE_STOPPED)

    def test_22_private_capture_ui_served_and_postgres_schema_derives(self):
        req = request.Request(f"http://127.0.0.1:{self.port}/ops/private-capture")
        with request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode()
            self.assertEqual(resp.status, 200)
        self.assertIn("Private capture session — Browser source not published", html)
        self.assertIn("No third-party live publish", html)
        # Script is external (CSP); verify local preview only — no publish SDKs.
        req_js = request.Request(f"http://127.0.0.1:{self.port}/private_capture.js")
        with request.urlopen(req_js, timeout=5) as resp:
            js = resp.read().decode()
            self.assertEqual(resp.status, 200)
        self.assertIn("getUserMedia", js)
        self.assertNotIn("cloudflare", js.lower())
        self.assertNotIn("restream", js.lower())
        self.assertNotIn("/api/events/", js)  # no lifecycle transition calls

        # Postgres schema derivation includes live_sessions (no live PG needed).
        from backend.db import SCHEMA, _postgres_schema
        self.assertIn("CREATE TABLE IF NOT EXISTS live_sessions", SCHEMA)
        pg = _postgres_schema()
        self.assertIn("CREATE TABLE IF NOT EXISTS live_sessions", pg)
        self.assertIn("idx_live_sessions_actor_idempotency", pg)


if __name__ == "__main__":
    unittest.main()
