"""Hosted media rail, viewer sessions, Merkle settlement, XRPL adapter.

Uses the deterministic demo provider only. These tests never call Cloudflare.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.control_plane import (
    AuthError, ConflictError, ControlPlane, ForbiddenError, NotFoundError,
)
from backend.db import Database, dumps
from backend.http_server import make_http_server
from backend.media_providers.cloudflare import CloudflareProvider
from backend.media_providers.demo import DemoProvider, live_input_create_body
from backend.merkle import hash_canonical, merkle_root, verify_proof
from backend.seed import seed_if_empty
from backend.xrpl_adapter import XrplAdapter, assert_payload_clean, commitment_payload


class RecordingProvider(DemoProvider):
    def __init__(self):
        super().__init__()
        self.playback_calls = 0
        self.hls = False

    def playback_url(self, event, expires_at):
        self.playback_calls += 1
        if self.hls:
            return "https://customer-test.cloudflarestream.com/tok/manifest/video.m3u8", "hls"
        return super().playback_url(event, expires_at)


def build_cp(provider=None, **cfg):
    defaults = dict(
        env="development",
        allowed_origins=["http://127.0.0.1:8000"],
        heartbeat_timeout=12,
        lease_ttl=60,
        cf_webhook_secret="test-webhook-secret",
        media_provider="demo",
        viewer_heartbeat_interval=15,
        viewer_stale_after=90,
        xrpl_mode="demo",
        token_secret="three-zone-demo-token-secret-CHANGE-ME-0000000000",
    )
    defaults.update(cfg)
    config = Config(**defaults)
    db = Database(":memory:")
    seed_if_empty(db)
    return ControlPlane(db, config, provider=provider or RecordingProvider())


class CreatePayloadTests(unittest.TestCase):
    def test_01_create_payload_flags(self):
        body = live_input_create_body(
            {"event_id": "evt_x", "title": "Game"},
            allowed_origins=["https://watch.example"],
            delete_after_days=365,
            prefer_low_latency=False,
        )
        self.assertEqual(body["recording"]["mode"], "automatic")
        self.assertTrue(body["recording"]["requireSignedURLs"])
        self.assertEqual(body["recording"]["allowedOrigins"], ["watch.example"])
        self.assertEqual(body["deleteRecordingAfterDays"], 365)
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        cp.provision_media("evt_mw_hockey", owner)
        self.assertEqual(cp.provider.last_create_body["recording"]["mode"], "automatic")
        self.assertTrue(cp.provider.last_create_body["recording"]["requireSignedURLs"])


class SecretHygieneTests(unittest.TestCase):
    def test_02_no_keys_in_audit_or_event_json(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        issued = cp.provision_media("evt_mw_hockey", owner)
        self.assertIn("stream_key", issued)
        event = cp.get_event("evt_mw_hockey", owner)
        blob = json.dumps(event)
        self.assertNotIn(issued["stream_key"], blob)
        self.assertNotIn("stream_key", blob)
        rows = cp.db.query("SELECT action, detail FROM audit")
        for row in rows:
            self.assertNotIn("stream_key", row["action"])
            self.assertNotIn(issued["stream_key"], row["detail"])
            self.assertNotIn("stream_key", row["detail"])
        chained = cp.db.query("SELECT payload FROM audit_events")
        for row in chained:
            self.assertNotIn(issued["stream_key"], row["payload"])
            self.assertNotIn("stream_key", row["payload"].lower())

    def test_03_one_input_per_event(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        cp.provision_media("evt_mw_hockey", owner)
        with self.assertRaises(ConflictError) as ctx:
            cp.provision_media("evt_mw_hockey", owner)
        self.assertEqual(ctx.exception.code, "already_provisioned")


class WebhookTests(unittest.TestCase):
    def test_04_webhook_green_promotes_live(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        issued = cp.provision_media("evt_mw_hockey", owner)
        result = cp.handle_provider_webhook(
            {"eventType": "connected", "data": {"liveInput": issued["input_id"]}, "timestamp": "t1"},
            "test-webhook-secret",
        )
        self.assertEqual(cp.get_event_row("evt_mw_hockey")["status"], "live")
        self.assertEqual(result["provider_state"], "connected")

    def test_05_webhook_yellow_does_not_auto_start(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        issued = cp.provision_media("evt_e_lacrosse", owner)
        cp.handle_provider_webhook(
            {"eventType": "connected", "data": {"liveInput": issued["input_id"]}, "timestamp": "t1"},
            "test-webhook-secret",
        )
        self.assertEqual(cp.get_event_row("evt_e_lacrosse")["status"], "yellow")

    def test_06_unknown_input_ignored_and_audited(self):
        cp = build_cp()
        result = cp.handle_provider_webhook(
            {"eventType": "connected", "data": {"liveInput": "no-such-input"}, "timestamp": "t9"},
            "test-webhook-secret",
        )
        self.assertTrue(result["ignored"])
        found = cp.db.query_one(
            "SELECT * FROM audit WHERE action='MEDIA_PROVIDER_STATUS' AND detail LIKE '%unknown_input%'"
        )
        self.assertIsNotNone(found)

    def test_07_bad_webhook_secret_rejected(self):
        cp = build_cp()
        with self.assertRaises(AuthError):
            cp.handle_provider_webhook({"eventType": "connected"}, "wrong")


class PlaybackPdpTests(unittest.TestCase):
    def test_08_playback_denials_skip_provider_url(self):
        provider = RecordingProvider()
        cp = build_cp(provider=provider)
        viewer = cp.get_user("demo-viewer")
        with self.assertRaises(ForbiddenError):
            cp.request_playback("evt_w_baseball", viewer)
        self.assertEqual(provider.playback_calls, 0)

    def test_09_hls_url_only_after_pdp(self):
        provider = RecordingProvider()
        provider.hls = True
        cp = build_cp(provider=provider)
        viewer = cp.get_user("demo-viewer")
        res = cp.request_playback("evt_mw_basketball", viewer)
        self.assertEqual(provider.playback_calls, 1)
        self.assertEqual(res["media_type"], "hls")
        self.assertTrue(res["media_url"].endswith(".m3u8"))
        self.assertIn("lease_token", res)

    def test_10_http_playback_json_has_no_lease_token(self):
        provider = RecordingProvider()
        provider.hls = True
        cp = build_cp(provider=provider, http_host="127.0.0.1", http_port=0)
        login = cp.demo_login("demo-viewer")
        httpd = make_http_server(cp.config, cp, "/tmp")
        try:
            host, port = httpd.server_address
            import threading
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/events/evt_mw_basketball/playback-session",
                data=b"{}",
                method="POST",
                headers={
                    "Authorization": "Bearer " + login["session_token"],
                    "Content-Type": "application/json",
                    "Origin": "http://127.0.0.1:8000",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
            self.assertNotIn("lease_token", body)
            self.assertIn("lease_id", body)
            self.assertEqual(body["media_type"], "hls")
        finally:
            httpd.shutdown()
            httpd.server_close()


class ViewSessionTests(unittest.TestCase):
    def test_11_session_heartbeat_and_cap(self):
        cp = build_cp()
        viewer = cp.get_user("demo-viewer")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        session = cp.start_view_session("evt_mw_basketball", viewer, lease["lease_id"])
        first = cp.view_heartbeat(session["session_id"], viewer, {
            "seq": 1, "playing": True, "page_visible": True, "position_seconds": 1,
        })
        self.assertGreaterEqual(first["credited_seconds"], 0)
        dup = cp.view_heartbeat(session["session_id"], viewer, {
            "seq": 1, "playing": True, "page_visible": True,
        })
        self.assertTrue(dup["duplicate"])
        cp.db.execute(
            "UPDATE view_sessions SET last_heartbeat_at=? WHERE session_id=?",
            (time.time() - 30, session["session_id"]),
        )
        jumped = cp.view_heartbeat(session["session_id"], viewer, {
            "seq": 2, "playing": True, "page_visible": True,
        })
        self.assertLessEqual(jumped["credited_seconds"], 15 * 1.5 + 0.01)
        hidden = cp.view_heartbeat(session["session_id"], viewer, {
            "seq": 3, "playing": True, "page_visible": False,
        })
        self.assertEqual(hidden["credited_seconds"], 0)

    def test_12_revoke_fails_heartbeat_and_closes(self):
        cp = build_cp()
        viewer = cp.get_user("demo-viewer")
        owner = cp.get_user("demo-owner")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        session = cp.start_view_session("evt_mw_basketball", viewer, lease["lease_id"])
        cp.revoke_rights("evt_mw_basketball", owner, "stop")
        closed = cp.db.query_one("SELECT * FROM view_sessions WHERE session_id=?", (session["session_id"],))
        self.assertEqual(closed["state"], "closed")
        self.assertEqual(closed["close_reason"], "rights_revoked")
        with self.assertRaises(ForbiddenError):
            cp.view_heartbeat(session["session_id"], viewer, {"seq": 1, "playing": True, "page_visible": True})
        with self.assertRaises(ForbiddenError):
            cp.request_playback("evt_mw_basketball", viewer)

    def test_13_stale_closer(self):
        cp = build_cp()
        viewer = cp.get_user("demo-viewer")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        session = cp.start_view_session("evt_mw_basketball", viewer, lease["lease_id"])
        cp.db.execute(
            "UPDATE view_sessions SET last_heartbeat_at=? WHERE session_id=?",
            (time.time() - 120, session["session_id"]),
        )
        n = cp.close_stale_view_sessions("evt_mw_basketball")
        self.assertEqual(n, 1)
        row = cp.db.query_one("SELECT * FROM view_sessions WHERE session_id=?", (session["session_id"],))
        self.assertEqual(row["close_reason"], "stale")
        self.assertIsNotNone(row["digest"])

    def test_13b_concurrent_start_reuses_one_open_session(self):
        """Two concurrent starts must not mint two open sessions for one viewer."""
        import threading
        cp = build_cp()
        viewer = cp.get_user("demo-viewer")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        results = []
        errors = []
        barrier = threading.Barrier(8)

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(cp.start_view_session("evt_mw_basketball", viewer, lease["lease_id"]))
            except Exception as exc:  # pragma: no cover - surfaced via assert
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        session_ids = {r["session_id"] for r in results}
        self.assertEqual(len(session_ids), 1)
        open_rows = cp.db.query(
            "SELECT * FROM view_sessions WHERE event_id=? AND user_id=? AND state='open'",
            ("evt_mw_basketball", viewer["user_id"]),
        )
        self.assertEqual(len(open_rows), 1)
        # Unique partial index must reject a second open row even outside the helper.
        with self.assertRaises(Exception):
            cp.db.execute(
                "INSERT INTO view_sessions(session_id,event_id,user_id,pseudonym,lease_id,rights_id,"
                "rights_version,started_at,ended_at,last_seq,last_heartbeat_at,qualified_seconds,"
                "state,close_reason,digest,canonical_json,property_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("VS-dup", "evt_mw_basketball", viewer["user_id"], "x", lease["lease_id"],
                 None, 1, time.time(), None, 0, time.time(), 0, "open", None, None, None, "school_lincoln"),
            )

    def test_13c_dedupe_migrates_legacy_duplicate_open_sessions(self):
        cp = build_cp()
        viewer = cp.get_user("demo-viewer")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        # Drop the unique index, insert a legacy duplicate, then re-init schema.
        cp.db.execute("DROP INDEX IF EXISTS idx_view_sessions_one_open")
        stamp = time.time()
        for sid in ("VS-legacy-a", "VS-legacy-b"):
            cp.db.execute(
                "INSERT INTO view_sessions(session_id,event_id,user_id,pseudonym,lease_id,rights_id,"
                "rights_version,started_at,ended_at,last_seq,last_heartbeat_at,qualified_seconds,"
                "state,close_reason,digest,canonical_json,property_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, "evt_mw_basketball", viewer["user_id"], "x", lease["lease_id"],
                 None, 1, stamp, None, 0, stamp, 0, "open", None, None, None, "school_lincoln"),
            )
        open_before = cp.db.query(
            "SELECT session_id FROM view_sessions WHERE event_id=? AND user_id=? AND state='open' "
            "ORDER BY session_id",
            ("evt_mw_basketball", viewer["user_id"]),
        )
        self.assertGreaterEqual(len(open_before), 2)
        cp.db.init_schema()
        open_after = cp.db.query(
            "SELECT session_id FROM view_sessions WHERE event_id=? AND user_id=? AND state='open'",
            ("evt_mw_basketball", viewer["user_id"]),
        )
        self.assertEqual(len(open_after), 1)
        closed = cp.db.query(
            "SELECT close_reason FROM view_sessions WHERE session_id='VS-legacy-b'"
        )
        self.assertEqual(closed[0]["close_reason"], "duplicate_open")


class ReplayPendingTests(unittest.TestCase):
    def test_14_end_sets_replay_pending_until_ready(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        cp.provision_media("evt_mw_basketball", owner)
        ended = cp.media_end("evt_mw_basketball", operator=owner)
        self.assertEqual(ended["status"], "replay")
        self.assertTrue(ended["replay_pending"])
        self.assertFalse(ended["replay_available"])
        status = cp.media_status("evt_mw_basketball", owner)
        self.assertNotIn("stream_key", status)
        cp.provider.mark_replay_ready("evt_mw_basketball")
        synced = cp.sync_media("evt_mw_basketball", owner)
        self.assertFalse(synced["replay_pending"])
        self.assertTrue(synced["replay_available"])


class SettlementTests(unittest.TestCase):
    def _closed_session(self, cp, event_id="evt_mw_basketball"):
        viewer = cp.get_user("demo-viewer")
        owner = cp.get_user("demo-owner")
        lease = cp.request_playback(event_id, viewer)
        session = cp.start_view_session(event_id, viewer, lease["lease_id"])
        cp.view_heartbeat(session["session_id"], viewer, {
            "seq": 1, "playing": True, "page_visible": True,
        })
        cp.end_view_session(session["session_id"], viewer, "pagehide")
        return owner, session

    def test_15_deterministic_session_digest_and_merkle_proof(self):
        cp = build_cp()
        owner, session = self._closed_session(cp)
        row = cp.db.query_one("SELECT * FROM view_sessions WHERE session_id=?", (session["session_id"],))
        expected = hash_canonical(json.loads(row["canonical_json"]))
        self.assertEqual(row["digest"], expected)
        manifest = cp.settlement_manifest("evt_mw_basketball", owner)
        self.assertEqual(manifest["session_count"], 1)
        proof = cp.settlement_session_proof(
            "school_lincoln", manifest["settlement_id"], session["session_id"], owner,
        )
        self.assertTrue(proof["included"])
        self.assertTrue(verify_proof(proof["digest"], proof["proof"], proof["merkle_root"]))

    def test_16_settlement_root_stability(self):
        cp = build_cp()
        owner, _ = self._closed_session(cp)
        first = cp.settlement_manifest("evt_mw_basketball", owner)
        second = cp.settlement_manifest("evt_mw_basketball", owner)
        self.assertEqual(first["merkle_root"], second["merkle_root"])
        self.assertEqual([s["digest"] for s in first["sessions"]],
                         [s["digest"] for s in second["sessions"]])

    def test_17_mutation_fails_verify(self):
        cp = build_cp()
        owner, _ = self._closed_session(cp)
        manifest = cp.settlement_manifest("evt_mw_basketball", owner)
        cp.db.execute(
            "UPDATE settlement_leaves SET digest=? WHERE settlement_id=?",
            ("0" * 64, manifest["settlement_id"]),
        )
        result = cp.verify_property_settlement("school_lincoln", manifest["settlement_id"], owner)
        self.assertEqual(result["result"], "MISMATCH")

    def test_18_property_isolation(self):
        cp = build_cp()
        owner, _ = self._closed_session(cp)
        manifest = cp.settlement_manifest("evt_mw_basketball", owner)
        with self.assertRaises(NotFoundError):
            cp.get_property_settlement("school_lakeside", manifest["settlement_id"], owner)
        listed = cp.list_property_settlements("school_lakeside", owner)
        ids = {s["settlement_id"] for s in listed}
        self.assertNotIn(manifest["settlement_id"], ids)

    def test_19_sessions_are_pseudonymous(self):
        cp = build_cp()
        owner, session = self._closed_session(cp)
        manifest = cp.settlement_manifest("evt_mw_basketball", owner)
        rows = cp.list_settlement_sessions("school_lincoln", manifest["settlement_id"], owner)
        blob = json.dumps(rows)
        self.assertNotIn("demo-viewer", blob)
        self.assertNotIn("user_id", blob)
        self.assertEqual(rows[0]["session_id"], session["session_id"])
        self.assertTrue(rows[0]["pseudonym"])


class XrplTests(unittest.TestCase):
    def test_20_xrpl_payload_hygiene(self):
        payload = commitment_payload({
            "settlement_id": "SET-1",
            "manifest_digest": "abc",
            "merkle_root": "def",
            "session_count": 1,
            "qualified_seconds": 10,
            "property_id": "school_lincoln",
            "event_id": "evt_mw_basketball",
        })
        assert_payload_clean(payload)
        blob = json.dumps(payload).lower()
        for needle in ("email", "stream_key", "signing_secret", "api_token", "heartbeat"):
            self.assertNotIn(needle, blob)

    def test_21_demo_receipt_is_labeled_simulated(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        viewer = cp.get_user("demo-viewer")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        session = cp.start_view_session("evt_mw_basketball", viewer, lease["lease_id"])
        cp.end_view_session(session["session_id"], viewer, "pagehide")
        manifest = cp.settlement_manifest("evt_mw_basketball", owner)
        self.assertTrue(manifest["publication"]["simulated"])
        self.assertTrue(manifest["publication"]["tx_hash"].startswith("DEMO-"))
        verify = cp.verify_property_settlement("school_lincoln", manifest["settlement_id"], owner)
        self.assertEqual(verify["result"], "MATCH")
        self.assertTrue(verify["simulated"])

    def test_22_submitted_is_not_validated(self):
        calls = {"submit": 0, "tx": 0}

        def rpc(method, params):
            if method == "submit":
                calls["submit"] += 1
                return {"tx_hash": "HASH1", "ledger_index": 9}
            calls["tx"] += 1
            return {"validated": False}

        cfg = Config(
            env="development", xrpl_mode="testnet", xrpl_rpc_url="http://xrpl.local",
            xrpl_audit_account="rTEST", xrpl_signing_secret="sTESTSECRET",
            allowed_origins=["http://127.0.0.1:8000"],
        )
        db = Database(":memory:")
        adapter = XrplAdapter(cfg, rpc=rpc)
        settlement = {
            "settlement_id": "SET-live", "manifest_digest": "aa", "merkle_root": "bb",
            "session_count": 0, "qualified_seconds": 0, "property_id": "p", "event_id": "e",
        }
        row = adapter.publish(db, settlement)
        self.assertEqual(row["status"], "submitted")
        self.assertNotEqual(row["status"], "validated")
        self.assertEqual(row["tx_hash"], "HASH1")
        self.assertFalse(row["simulated"])

    def test_23_retry_same_commitment(self):
        state = {"validated": False}

        def rpc(method, params):
            if method == "submit":
                return {"tx_hash": "HASH2", "ledger_index": 1}
            return {"validated": state["validated"], "ledger_index": 2}

        cfg = Config(
            env="development", xrpl_mode="testnet", xrpl_rpc_url="http://xrpl.local",
            xrpl_audit_account="rTEST", xrpl_signing_secret="sTESTSECRET",
            allowed_origins=["http://127.0.0.1:8000"],
        )
        db = Database(":memory:")
        adapter = XrplAdapter(cfg, rpc=rpc)
        settlement = {
            "settlement_id": "SET-retry", "manifest_digest": "aa", "merkle_root": "bb",
            "session_count": 1, "qualified_seconds": 4, "property_id": "p", "event_id": "e",
        }
        first = adapter.publish(db, settlement)
        commitment = first["commitment"]
        pub_id = first["publication_id"]
        second = adapter.retry(db, settlement)
        self.assertEqual(second["commitment"], commitment)
        self.assertEqual(second["publication_id"], pub_id)
        state["validated"] = True
        third = adapter.retry(db, settlement)
        self.assertEqual(third["status"], "validated")
        self.assertEqual(third["publication_id"], pub_id)


class AnalyticsTests(unittest.TestCase):
    def test_24_analytics_snapshot_does_not_overwrite_tz(self):
        from backend.media_providers.base import AnalyticsSnapshot
        provider = RecordingProvider()
        cp = build_cp(provider=provider)
        owner = cp.get_user("demo-owner")
        viewer = cp.get_user("demo-viewer")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        session = cp.start_view_session("evt_mw_basketball", viewer, lease["lease_id"])
        cp.db.execute(
            "UPDATE view_sessions SET last_heartbeat_at=? WHERE session_id=?",
            (time.time() - 10, session["session_id"]),
        )
        cp.view_heartbeat(session["session_id"], viewer, {
            "seq": 1, "playing": True, "page_visible": True,
        })
        first = cp.snapshot_analytics("evt_mw_basketball")
        self.assertEqual(first["status"], "PROVIDER_DATA_PENDING")
        tz = first["tz_qualified_seconds"]
        provider.analytics = AnalyticsSnapshot(
            video_id="v1", minutes_viewed=12.0, window_start=0, window_end=1,
            available=True, raw_summary={},
        )
        second = cp.snapshot_analytics("evt_mw_basketball")
        self.assertEqual(second["status"], "compared")
        rows = cp.db.query("SELECT * FROM provider_analytics_snapshots ORDER BY created_at")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["tz_qualified_seconds"], tz)
        self.assertEqual(rows[1]["tz_qualified_seconds"], tz)
        self.assertEqual(rows[0]["status"], "PROVIDER_DATA_PENDING")


class CloudflareAdapterTests(unittest.TestCase):
    def test_25_signed_token_expiry_not_past_lease(self):
        calls = []

        class FakeResp:
            def __init__(self, payload):
                self._payload = json.dumps(payload).encode()

            def read(self):
                return self._payload

        def opener(req):
            calls.append((req.get_method(), req.full_url, req.data))
            if req.full_url.endswith("/token"):
                return FakeResp({"result": {"token": "SIGNEDTOKEN"}})
            return FakeResp({"result": {}})

        cfg = Config(
            env="development", cf_account_id="acc", cf_api_token="tok",
            cf_customer_code="abc123", allowed_origins=["http://127.0.0.1:8000"],
        )
        provider = CloudflareProvider(cfg, opener=opener)
        expires = time.time() + 40
        url, kind = provider.playback_url(
            {"provider_video_id": "vid", "event_id": "evt_x"}, expires,
        )
        self.assertEqual(kind, "hls")
        self.assertIn("SIGNEDTOKEN", url)
        self.assertTrue(url.endswith("manifest/video.m3u8"))
        body = json.loads(calls[-1][2].decode())
        self.assertLessEqual(body["exp"], int(expires))
        self.assertLessEqual(body["lifetime"], 40)


class ConfigTests(unittest.TestCase):
    def test_26_public_config_hides_secrets(self):
        cfg = Config(
            env="demo", cf_api_token="cf-secret-token", xrpl_signing_secret="xrpl-secret",
            media_service_key="media-secret", token_secret="token-secret-value",
            cf_customer_code="code1", allowed_origins=["http://localhost"],
        )
        public = json.dumps(cfg.public_config())
        self.assertNotIn("cf-secret-token", public)
        self.assertNotIn("xrpl-secret", public)
        self.assertNotIn("media-secret", public)
        self.assertNotIn("token-secret-value", public)
        self.assertEqual(cfg.public_config()["media_provider"], "demo")

    def test_27_default_provider_is_demo(self):
        os.environ.pop("TZ_MEDIA_PROVIDER", None)
        os.environ.pop("TZ_LIVE_MEDIA_PROVIDER", None)
        os.environ.pop("TZ_UGC_MEDIA_PROVIDER", None)
        os.environ.pop("TZ_PLAYBACK_LEASE_SECONDS", None)
        os.environ.pop("TZ_LEASE_TTL", None)
        os.environ.pop("CLOUDFLARE", None)
        cfg = Config.from_env()
        self.assertEqual(cfg.media_provider, "demo")
        self.assertEqual(cfg.lease_ttl, 60)

    def test_27b_cloudflare_env_alias_is_not_public(self):
        os.environ["CLOUDFLARE"] = "cf-token-alias-value"
        try:
            cfg = Config.from_env()
            self.assertEqual(cfg.cf_api_token, "cf-token-alias-value")
            self.assertNotIn("cf-token-alias-value", str(cfg.public_config()))
        finally:
            os.environ.pop("CLOUDFLARE", None)

    def test_27c_live_and_ugc_providers_are_independent(self):
        from backend.media_provider import FakeProvider, build_provider
        from backend.media_providers import get_provider
        from backend.media_providers.demo import DemoProvider

        fake = Config(media_provider="fake")
        self.assertEqual(fake.live_provider_name(), "demo")
        self.assertEqual(fake.ugc_provider_name(), "fake")
        self.assertEqual(fake.media_provider, "demo")
        self.assertIsInstance(get_provider(fake), DemoProvider)
        self.assertIsInstance(build_provider(fake), FakeProvider)

        split = Config(live_media_provider="cloudflare", ugc_media_provider="fake")
        self.assertEqual(split.live_provider_name(), "cloudflare")
        self.assertEqual(split.ugc_provider_name(), "fake")
        self.assertEqual(split.media_provider, "cloudflare")

        os.environ["TZ_MEDIA_PROVIDER"] = "fake"
        os.environ.pop("TZ_LIVE_MEDIA_PROVIDER", None)
        os.environ.pop("TZ_UGC_MEDIA_PROVIDER", None)
        try:
            cfg = Config.from_env()
            self.assertEqual(cfg.live_provider_name(), "demo")
            self.assertEqual(cfg.ugc_provider_name(), "fake")
            self.assertEqual(cfg.media_provider, "demo")
        finally:
            os.environ.pop("TZ_MEDIA_PROVIDER", None)


class AuditorRoleTests(unittest.TestCase):
    def test_28_auditor_scoped_to_properties(self):
        cp = build_cp()
        cp.db.execute(
            "INSERT INTO users(user_id,display_name,role,account_state,subscription,zones,packages,"
            "destinations,password_hash,properties) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("aud-1", "Auditor", "auditor", "active", "active", "[]", "[]", "[]", "",
             dumps(["school_lincoln"])),
        )
        auditor = cp.get_user("aud-1")
        owner = cp.get_user("demo-owner")
        viewer = cp.get_user("demo-viewer")
        lease = cp.request_playback("evt_mw_basketball", viewer)
        session = cp.start_view_session("evt_mw_basketball", viewer, lease["lease_id"])
        cp.end_view_session(session["session_id"], viewer, "pagehide")
        manifest = cp.settlement_manifest("evt_mw_basketball", owner)
        listed = cp.list_property_settlements("school_lincoln", auditor)
        self.assertEqual(listed[0]["settlement_id"], manifest["settlement_id"])
        with self.assertRaises(ForbiddenError):
            cp.list_property_settlements("school_lakeside", auditor)


class RotateAndDisconnectTests(unittest.TestCase):
    def test_29_rotate_returns_key_once_status_does_not(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        cp.provision_media("evt_mw_hockey", owner)
        rotated = cp.rotate_media_key("evt_mw_hockey", owner)
        self.assertIn("stream_key", rotated)
        status = cp.media_status("evt_mw_hockey", owner)
        self.assertNotIn("stream_key", status)
        blob = json.dumps(dict(cp.get_event_row("evt_mw_hockey")))
        self.assertNotIn(rotated["stream_key"], blob)

    def test_30_disconnect_does_not_clear_rights(self):
        cp = build_cp()
        owner = cp.get_user("demo-owner")
        issued = cp.provision_media("evt_mw_hockey", owner)
        cp.handle_provider_webhook(
            {"eventType": "connected", "data": {"liveInput": issued["input_id"]}, "timestamp": "c"},
            "test-webhook-secret",
        )
        cp.handle_provider_webhook(
            {"eventType": "disconnected", "data": {"liveInput": issued["input_id"]}, "timestamp": "d"},
            "test-webhook-secret",
        )
        self.assertIsNotNone(cp.current_rights("evt_mw_hockey"))
        self.assertEqual(cp.get_event_row("evt_mw_hockey")["provider_state"], "disconnected")
        self.assertEqual(cp.get_event_row("evt_mw_hockey")["status"], "live")


class HttpWebhookBodyTests(unittest.TestCase):
    def test_31_webhook_accepts_large_body(self):
        cp = build_cp(http_host="127.0.0.1", http_port=0)
        owner = cp.get_user("demo-owner")
        issued = cp.provision_media("evt_mw_hockey", owner)
        httpd = make_http_server(cp.config, cp, "/tmp")
        try:
            port = httpd.server_address[1]
            import threading
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            payload = {
                "eventType": "connected",
                "timestamp": "big",
                "data": {"liveInput": issued["input_id"], "pad": "x" * 80_000},
            }
            raw = json.dumps(payload).encode()
            self.assertGreater(len(raw), 64 * 1024)
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/media/webhooks/cloudflare",
                data=raw, method="POST",
                headers={"Content-Type": "application/json", "X-Webhook-Secret": "test-webhook-secret"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
            self.assertTrue(body["ok"])
            self.assertEqual(cp.get_event_row("evt_mw_hockey")["status"], "live")
        finally:
            httpd.shutdown()
            httpd.server_close()


class SmokePathTests(unittest.TestCase):
    def test_32_event_to_manifest_smoke(self):
        provider = RecordingProvider()
        cp = build_cp(provider=provider)
        owner = cp.get_user("demo-owner")
        viewer = cp.get_user("demo-viewer")
        issued = cp.provision_media("evt_mw_hockey", owner)
        self.assertTrue(issued["stream_key"])
        cp.handle_provider_webhook(
            {"eventType": "connected", "data": {"liveInput": issued["input_id"]}, "timestamp": "s1"},
            "test-webhook-secret",
        )
        self.assertEqual(cp.get_event_row("evt_mw_hockey")["status"], "live")
        lease = cp.request_playback("evt_mw_hockey", viewer)
        self.assertTrue(lease["allow"])
        session = cp.start_view_session("evt_mw_hockey", viewer, lease["lease_id"])
        cp.view_heartbeat(session["session_id"], viewer, {
            "seq": 1, "playing": True, "page_visible": True,
        })
        cp.revoke_rights("evt_mw_hockey", owner, "incident")
        with self.assertRaises(ForbiddenError):
            cp.request_playback("evt_mw_hockey", viewer)
        cp.restore_rights("evt_mw_hockey", owner)
        cp.media_end("evt_mw_hockey", operator=owner)
        ended = cp.get_event("evt_mw_hockey", owner)
        self.assertTrue(ended["replay_pending"])
        provider.mark_replay_ready("evt_mw_hockey")
        synced = cp.sync_media("evt_mw_hockey", owner)
        self.assertTrue(synced["replay_available"])
        # Replay is playable; start a session that can settle.
        lease2 = cp.request_playback("evt_mw_hockey", viewer)
        session2 = cp.start_view_session("evt_mw_hockey", viewer, lease2["lease_id"])
        cp.end_view_session(session2["session_id"], viewer, "pagehide")
        manifest = cp.settlement_manifest("evt_mw_hockey", owner)
        self.assertTrue(manifest["manifest_digest"])
        self.assertTrue(manifest["merkle_root"])
        self.assertTrue(manifest["publication"]["tx_hash"].startswith("DEMO-"))
        verify = cp.verify_property_settlement("school_lincoln", manifest["settlement_id"], owner)
        self.assertEqual(verify["result"], "MATCH")



class LiveReadinessTests(unittest.TestCase):
    def test_demo_rail_is_ready_with_warnings(self):
        from backend.live_readiness import readiness
        cfg = Config(
            env="development",
            allowed_origins=["http://127.0.0.1:8000"],
            media_provider="demo",
            public_base_url="http://127.0.0.1:8000",
            xrpl_mode="demo",
        )
        report = readiness(cfg)
        self.assertTrue(report["ready_to_publish_live"])
        self.assertTrue(any("demo rail" in w for w in report["warnings"]))

    def test_cloudflare_missing_fields_block(self):
        from backend.live_readiness import readiness
        cfg = Config(
            env="development",
            allowed_origins=["http://127.0.0.1:8000"],
            media_provider="cloudflare",
            public_base_url="http://127.0.0.1:8000",
            xrpl_mode="demo",
        )
        report = readiness(cfg)
        self.assertFalse(report["ready_to_publish_live"])
        self.assertGreaterEqual(len(report["blockers"]), 1)

    def test_live_readiness_route_is_operator_gated(self):
        from backend.control_plane import SITE_ROUTES
        row = next(r for r in SITE_ROUTES if r["path"] == "/api/ops/live-readiness")
        self.assertEqual(row["tier"], "worker")


if __name__ == "__main__":
    unittest.main()
