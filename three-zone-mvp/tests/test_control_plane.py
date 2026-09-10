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
    ConflictError, ControlPlane, ForbiddenError, SITE_ROUTES, TIERS,
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
        self.admin = self.cp.get_user("demo-owner")

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
        self.admin = self.cp.get_user("demo-owner")

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
        self.admin = self.cp.get_user("demo-owner")

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


class RoleMatrixTests(unittest.TestCase):
    """Member (viewer) < worker (operator) < owner tier separation."""

    def setUp(self):
        self.cp = build_cp()
        self.member = self.cp.get_user("demo-viewer")
        self.worker = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")

    def test_seeded_roles(self):
        self.assertEqual(self.member["role"], "viewer")
        self.assertEqual(self.worker["role"], "operator")
        self.assertEqual(self.owner["role"], "owner")

    def test_existing_database_receives_new_demo_roles(self):
        self.cp.db.execute(
            "INSERT INTO users(user_id,display_name,role,account_state,subscription,"
            "zones,packages,destinations) VALUES (?,?,?,?,?,?,?,?)",
            ("demo-admin", "Legacy Admin", "admin", "active", "active", '["*"]', '["*"]', '["*"]'),
        )
        self.cp.db.execute(
            "DELETE FROM users WHERE user_id IN (?, ?)",
            ("demo-worker", "demo-owner"),
        )
        self.assertFalse(seed_if_empty(self.cp.db))
        self.assertEqual(self.cp.get_user("demo-worker")["role"], "operator")
        self.assertEqual(self.cp.get_user("demo-owner")["role"], "owner")
        self.assertIsNone(self.cp.get_user("demo-admin"))

    def test_member_cannot_operate(self):
        with self.assertRaises(ForbiddenError) as ctx:
            self.cp.require_operator(self.member)
        self.assertEqual(ctx.exception.code, "operator_required")

    def test_worker_can_operate_but_not_own(self):
        self.cp.require_operator(self.worker)  # no raise
        with self.assertRaises(ForbiddenError) as ctx:
            self.cp.require_owner(self.worker)
        self.assertEqual(ctx.exception.code, "owner_required")

    def test_owner_can_operate_and_own(self):
        self.cp.require_operator(self.owner)  # no raise
        self.cp.require_owner(self.owner)  # no raise

    def test_worker_can_create_event_member_cannot(self):
        created = self.cp.create_event(self.worker, {"title": "Worker Event", "zone": "west"})
        self.assertEqual(created["status"], "scheduled")
        with self.assertRaises(ForbiddenError):
            self.cp.create_event(self.member, {"title": "Nope", "zone": "west"})

    def test_audit_is_locally_preserved_before_verification_outbox(self):
        self.cp.audit_log("demo-owner", "rights.revoked", "evt_mw_basketball", {"reason": "test"})
        item = self.cp.verification_outbox(self.owner)[-1]["event"]
        self.assertEqual(item["organization_id"], "THREE_ZONE_KC")
        self.assertEqual(item["event_type"], "rights.revoked")
        self.assertEqual(item["source_system"], "three-zone-mvp")
        self.assertTrue(item["canonical_event_hash"])


class OwnerPortalTests(unittest.TestCase):
    """The owner back portal prints/exports every single thing."""

    def setUp(self):
        self.cp = build_cp()
        self.member = self.cp.get_user("demo-viewer")
        self.worker = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")

    def test_inventory_requires_owner(self):
        with self.assertRaises(ForbiddenError):
            self.cp.owner_inventory(self.member)
        with self.assertRaises(ForbiddenError):
            self.cp.owner_inventory(self.worker)

    def test_inventory_contains_everything(self):
        inv = self.cp.owner_inventory(self.owner)
        # Self-describing site model is present.
        self.assertEqual(len(inv["tiers"]), 3)
        self.assertEqual({t["tier"] for t in inv["tiers"]}, {"member", "worker", "owner"})
        self.assertEqual(inv["routes"], SITE_ROUTES)
        # Every user, event, and audit entry is dumped.
        self.assertEqual(inv["totals"]["users"], len(inv["users"]))
        self.assertEqual(inv["totals"]["events"], len(inv["events"]))
        self.assertEqual(inv["totals"]["audit_entries"], len(inv["audit"]))
        self.assertGreaterEqual(inv["totals"]["users"], 3)
        # No secrets leak through the environment block.
        env_blob = str(inv["environment"])
        self.assertNotIn("token_secret", env_blob)
        self.assertNotIn("CHANGE-ME", env_blob)

    def test_inventory_includes_full_rights_history(self):
        # Revoke then restore so evt has 2 rights versions; both must appear.
        self.cp.revoke_rights("evt_mw_basketball", self.owner, "dispute")
        self.cp.restore_rights("evt_mw_basketball", self.owner)
        inv = self.cp.owner_inventory(self.owner)
        ev = next(e for e in inv["events"] if e["event_id"] == "evt_mw_basketball")
        versions = ev["rights_versions"]
        self.assertEqual([r["version"] for r in versions], [1, 2])
        self.assertTrue(versions[0]["revoked"])
        self.assertTrue(versions[1]["active"])

    def test_route_map_matches_owner_endpoint(self):
        paths = {r["path"] for r in SITE_ROUTES}
        self.assertIn("/api/owner/inventory", paths)
        self.assertIn("/ops", paths)
        self.assertIn("/api/member/live", paths)
        self.assertIn("/api/auth/login", paths)
        self.assertIn("/api/auth/register", paths)
        self.assertIn("/api/owner/mastery", paths)
        self.assertIn("/api/owner/staff", paths)
        self.assertIn("/three-zone-mastery", paths)


class MasteryDocumentTests(unittest.TestCase):
    def test_mastery_article_covers_every_engine_and_the_blockchain(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "THREE_ZONE_MASTERY.md")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertGreater(len(text.split()), 3500)
        for needle in (
            "player is never the authority",
            "XRP Ledger",
            "xrpl_publications",
            "audit_events",
            "previous_event_hash",
            "Treasure",
            "pbkdf2",
            "tz_member_session",
            "tz_lease_",
            "socket_outbox",
            "evaluate_access",
            "validate_lease",
            "TZ-01",
            "TR-06",
            "ingest_scope",
            "rights_version_changed",
            "GET /api/owner/inventory",
            "WS",
            "member_verifications",
            "DEMO-",
        ):
            self.assertIn(needle, text)

    def test_mastery_renders_to_html(self):
        from backend.mastery import article_html, full_page_html, load_markdown
        md = load_markdown()
        html = article_html()
        self.assertIn("Three Zone Mastery", md)
        self.assertIn("<h1>", html)
        self.assertIn("XRP Ledger", html)
        page = full_page_html()
        self.assertIn("Print this guide", page)
        self.assertIn("<table>", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
