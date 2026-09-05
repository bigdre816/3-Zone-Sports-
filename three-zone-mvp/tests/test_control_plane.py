"""Domain tests for the Three-Zone control plane.

Covers: live lease issuance, zone denial, lifecycle ordering, automatic replay
transition, rights revocation invalidation, production-readiness guard,
event-scoped ingest credentials, and token tamper rejection.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import tokens
from backend.config import Config
from backend.control_plane import (
    ConflictError, ControlPlane, ForbiddenError,
)
from backend.db import Database
from backend.seed import seed_if_empty


def build_cp() -> ControlPlane:
    cfg = Config(env="development", allowed_origins=["http://127.0.0.1:8000"],
                 heartbeat_timeout=12, lease_ttl=90)
    db = Database(":memory:")
    seed_if_empty(db)
    return ControlPlane(db, cfg)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.cp = build_cp()
        self.viewer = self.cp.get_user("demo-viewer")
        self.admin = self.cp.get_user("demo-admin")

    def test_live_lease_issuance_and_validation(self):
        res = self.cp.request_playback("evt_mw_basketball", self.viewer)
        self.assertTrue(res["allow"])
        self.assertEqual(res["mode"], "live")
        check = self.cp.validate_lease("evt_mw_basketball", res["lease_token"])
        self.assertTrue(check["valid"])
        self.assertEqual(check["subject"], "demo-viewer")

    def test_zone_denial(self):
        # demo-viewer is entitled to midwest only; a west event must be denied.
        with self.assertRaises(ForbiddenError) as ctx:
            self.cp.request_playback("evt_w_baseball", self.viewer)
        self.assertEqual(ctx.exception.code, "zone_not_entitled")

    def test_rights_revocation_invalidates_lease(self):
        res = self.cp.request_playback("evt_mw_basketball", self.viewer)
        self.assertTrue(self.cp.validate_lease("evt_mw_basketball", res["lease_token"])["valid"])
        self.cp.revoke_rights("evt_mw_basketball", self.admin, "dispute")
        after = self.cp.validate_lease("evt_mw_basketball", res["lease_token"])
        self.assertFalse(after["valid"])
        self.assertEqual(after["reason"], "rights_unavailable")

    def test_restore_creates_new_version_and_reenables(self):
        self.cp.revoke_rights("evt_mw_basketball", self.admin, "dispute")
        event = self.cp.restore_rights("evt_mw_basketball", self.admin)
        self.assertEqual(event["rights"]["version"], 2)
        res = self.cp.request_playback("evt_mw_basketball", self.viewer)
        self.assertEqual(res["rights_version"], 2)

    def test_lease_bound_to_version_rejects_stale_after_restore(self):
        first = self.cp.request_playback("evt_mw_basketball", self.viewer)
        self.cp.revoke_rights("evt_mw_basketball", self.admin, "dispute")
        self.cp.restore_rights("evt_mw_basketball", self.admin)
        stale = self.cp.validate_lease("evt_mw_basketball", first["lease_token"])
        self.assertFalse(stale["valid"])
        self.assertEqual(stale["reason"], "rights_version_changed")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.cp = build_cp()
        self.admin = self.cp.get_user("demo-admin")

    def test_illegal_transition_rejected(self):
        # west football is 'scheduled'; jumping to live is illegal.
        with self.assertRaises(ConflictError) as ctx:
            self.cp.transition("evt_w_football", self.admin, "live")
        self.assertEqual(ctx.exception.code, "illegal_transition")

    def test_ordering_and_production_guard(self):
        eid = "evt_w_football"  # scheduled, no fresh heartbeat
        self.cp.transition(eid, self.admin, "gray")
        self.cp.transition(eid, self.admin, "yellow")
        with self.assertRaises(ConflictError) as ctx:
            self.cp.transition(eid, self.admin, "green")
        self.assertEqual(ctx.exception.code, "production_not_ready")
        # provide a fresh heartbeat, then green + live succeed
        issued = self.cp.issue_ingest_token(eid, self.admin, "primary")
        self.cp.record_heartbeat(eid, issued["ingest_token"], "primary", healthy=True)
        self.assertEqual(self.cp.transition(eid, self.admin, "green")["status"], "green")
        self.assertEqual(self.cp.transition(eid, self.admin, "live")["status"], "live")

    def test_media_end_transitions_live_to_replay(self):
        # basketball is live in the seed.
        event = self.cp.media_end("evt_mw_basketball", self.cp.config.media_service_key)
        self.assertEqual(event["status"], "replay")
        self.assertTrue(event["replay_available"])

    def test_media_end_requires_service_key(self):
        with self.assertRaises(ForbiddenError):
            self.cp.media_end("evt_mw_basketball", "wrong-key")


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.cp = build_cp()
        self.admin = self.cp.get_user("demo-admin")

    def test_ingest_token_is_event_and_source_scoped(self):
        issued = self.cp.issue_ingest_token("evt_mw_volleyball", self.admin, "primary")
        token = issued["ingest_token"]
        # correct scope works
        ok = self.cp.record_heartbeat("evt_mw_volleyball", token, "primary")
        self.assertTrue(ok["feed_healthy"])
        # wrong event is rejected
        with self.assertRaises(ForbiddenError) as ctx:
            self.cp.record_heartbeat("evt_mw_hockey", token, "primary")
        self.assertEqual(ctx.exception.code, "ingest_scope")
        # wrong source is rejected
        with self.assertRaises(ForbiddenError) as ctx2:
            self.cp.record_heartbeat("evt_mw_volleyball", token, "backup")
        self.assertEqual(ctx2.exception.code, "ingest_scope")


class TokenTamperTests(unittest.TestCase):
    def setUp(self):
        self.cp = build_cp()
        self.viewer = self.cp.get_user("demo-viewer")

    def test_tampered_session_rejected(self):
        good = tokens.sign(self.cp.config.token_secret, "session", {"sub": "demo-viewer"}, 60)
        tampered = good[:-2] + ("aa" if not good.endswith("aa") else "bb")
        with self.assertRaises(tokens.TokenError):
            tokens.verify(self.cp.config.token_secret, tampered, "session")

    def test_wrong_type_rejected(self):
        lease_like = tokens.sign(self.cp.config.token_secret, "lease", {"sub": "x"}, 60)
        with self.assertRaises(tokens.TokenError):
            tokens.verify(self.cp.config.token_secret, lease_like, "session")

    def test_tampered_lease_fails_media_validation(self):
        res = self.cp.request_playback("evt_mw_basketball", self.viewer)
        tampered = res["lease_token"][:-3] + "xyz"
        check = self.cp.validate_lease("evt_mw_basketball", tampered)
        self.assertFalse(check["valid"])
        self.assertEqual(check["reason"], "invalid_lease")


if __name__ == "__main__":
    unittest.main(verbosity=2)
