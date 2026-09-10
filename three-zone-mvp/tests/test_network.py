"""Member sports network: identity, PDP, uploads, Studio, social, and audit."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.control_plane import (
    AuthError, ControlPlane, ForbiddenError, SITE_ROUTES, ValidationError,
)
from backend.db import Database
from backend.identity import resolve_identity, resolve_identity_optional
from backend.media_provider import FakeProvider, build_provider
from backend.network import NetworkService, RateLimitError
from backend.portal import PortalService
from backend.seed import seed_if_empty


def build_net(provider=None):
    db = Database(":memory:")
    seed_if_empty(db)
    cfg = Config(env="demo", allowed_origins=["http://localhost"], media_provider="fake")
    cp = ControlPlane(db, cfg)
    portal = PortalService(cp)
    provider = provider or FakeProvider(webhook_secret=cfg.fake_webhook_secret)
    net = NetworkService(cp, portal, provider)
    return cp, portal, net, provider


class IdentityUnificationTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()

    def test_bearer_and_cookie_resolve_same_user(self):
        login = self.cp.password_login("demo-viewer", "change-me-viewer-local")
        cookie = self.portal.complete_auth("demo-viewer")
        from_bearer = resolve_identity(self.cp, self.portal, login["session_token"], None)
        from_cookie = resolve_identity(self.cp, self.portal, None, cookie["session_id"])
        self.assertEqual(from_bearer["user_id"], from_cookie["user_id"])
        self.assertEqual(from_bearer["user_id"], "demo-viewer")

    def test_optional_unsigned_is_none(self):
        self.assertIsNone(resolve_identity_optional(self.cp, self.portal, None, None))

    def test_missing_session_raises(self):
        with self.assertRaises(AuthError) as ctx:
            resolve_identity(self.cp, self.portal, None, None)
        self.assertEqual(ctx.exception.code, "missing_session")

    def test_login_rate_limit(self):
        for _ in range(8):
            self.net.check_login_rate("203.0.113.9")
        with self.assertRaises(RateLimitError) as ctx:
            self.net.check_login_rate("203.0.113.9")
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertEqual(ctx.exception.status, 429)
        self.net.check_login_rate("203.0.113.10")


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.worker = self.cp.get_user("demo-worker")

    def test_registration_creates_profile(self):
        created = self.cp.register_viewer("patfan", "password123", "Pat Fan")
        profile = self.net.ensure_profile(created["user"])
        self.assertEqual(profile["profile_type"], "fan")
        public = self.net.public_profile(profile)
        self.assertNotIn("user_id", public)
        self.assertNotIn("email", public)

    def test_member_cannot_self_assign_badge(self):
        with self.assertRaises(ForbiddenError) as ctx:
            self.net.update_own_profile(self.member, {"verification_badge": "verified_athlete"})
        self.assertEqual(ctx.exception.code, "badge_forbidden")
        verified = self.net.set_verification(self.worker, "prf_demo_viewer", "verified_athlete")
        self.assertEqual(verified["verification_badge"], "verified_athlete")


class UploadAndWebhookTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")

    def test_direct_upload_contract_has_no_provider_token(self):
        contract = self.net.create_upload(self.member, {"kind": "game", "idempotency_key": "g1"})
        blob = str(contract)
        self.assertIn("upload_url", contract)
        self.assertEqual(contract["upload_method"], "tus")
        self.assertTrue(contract["resumable"])
        self.assertNotIn("api_token", blob)
        self.assertNotIn("api_key", blob)
        self.assertNotIn("CLOUDFLARE", blob.upper())
        self.assertNotIn(self.cp.config.fake_webhook_secret, blob)
        again = self.net.create_upload(self.member, {"kind": "game", "idempotency_key": "g1"})
        self.assertEqual(again["upload_job_id"], contract["upload_job_id"])

    def test_webhook_signature_idempotency_and_stale_ignore(self):
        contract = self.net.create_upload(self.member, {"kind": "clip"})
        token = contract["upload_url"].rsplit("/", 1)[-1]
        first = self.net.complete_fake_upload(token, {"duration_seconds": 24})
        self.assertTrue(first["ok"])
        job = self.net.upload_status(self.member, contract["upload_job_id"])
        self.assertEqual(job["status"], "ready")
        payload = {
            "provider_event_id": "dup-event",
            "provider_uid": "unused",
            "status": "ready",
        }
        with self.assertRaises(AuthError):
            self.net.apply_webhook({}, payload)
        signed = dict(payload)
        signed["signature"] = self.provider._sign("dup-event", "unused", "ready")
        self.net.apply_webhook({}, signed)
        again = self.net.apply_webhook({}, signed)
        self.assertTrue(again.get("duplicate"))
        stale = {
            "provider_event_id": "stale-1",
            "provider_uid": self.cp.db.query_one(
                "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?",
                (contract["upload_job_id"],),
            )["provider_uid"],
            "status": "failed",
        }
        stale["signature"] = self.provider._sign(stale["provider_event_id"], stale["provider_uid"], "failed")
        ignored = self.net.apply_webhook({}, stale)
        self.assertEqual(ignored.get("ignored"), "stale")
        self.assertEqual(self.net.upload_status(self.member, contract["upload_job_id"])["status"], "ready")


class GameStudioTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.other = self.cp.register_viewer("otherfan", "password123", "Other")["user"]
        self.worker = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")

    def _ready_game(self, user=None, event_id=None, visibility="private"):
        user = user or self.member
        game = self.net.submit_game(user, {
            "sport": "basketball",
            "home_team_name": "Lincoln",
            "away_team_name": "Central",
            "rights_attestation": True,
            "event_id": event_id,
            "visibility": visibility,
            "level": "high school",
        })
        token = game["upload"]["upload_url"].rsplit("/", 1)[-1]
        self.net.complete_fake_upload(token, {"duration_seconds": 600})
        return self.net.game_view(user, game["game_id"])

    def test_attestation_required_and_no_auto_public(self):
        with self.assertRaises(ValidationError) as ctx:
            self.net.submit_game(self.member, {"sport": "basketball"})
        self.assertEqual(ctx.exception.code, "attestation_required")
        game = self._ready_game(visibility="public")
        self.assertEqual(game["visibility"], "private")
        self.assertEqual(game["processing_status"], "ready")
        self.assertEqual(game["verification_status"], "pending")

    def test_source_immutable_after_clip(self):
        game = self._ready_game()
        before = self.cp.db.query_one("SELECT * FROM games WHERE game_id=?", (game["game_id"],))
        clip = self.net.create_clip_definition(self.member, {
            "source_game_id": game["game_id"], "start_seconds": 10, "end_seconds": 30,
        })
        after = self.cp.db.query_one("SELECT * FROM games WHERE game_id=?", (game["game_id"],))
        self.assertEqual(before["media_asset_id"], after["media_asset_id"])
        self.assertEqual(before["duration_seconds"], after["duration_seconds"])
        self.assertEqual(clip["source_type"], "game_clip")
        rendered = self.net.render_clip(self.member, clip["clip_id"])
        self.assertEqual(rendered["publication_status"], "ready")
        after2 = self.cp.db.query_one("SELECT * FROM games WHERE game_id=?", (game["game_id"],))
        self.assertEqual(before["media_asset_id"], after2["media_asset_id"])

    def test_clip_bounds_and_max_duration(self):
        game = self._ready_game()
        with self.assertRaises(ValidationError):
            self.net.create_clip_definition(self.member, {
                "source_game_id": game["game_id"], "start_seconds": 40, "end_seconds": 20,
            })
        with self.assertRaises(ValidationError) as ctx:
            self.net.create_clip_definition(self.member, {
                "source_game_id": game["game_id"], "start_seconds": 0, "end_seconds": 120,
            })
        self.assertEqual(ctx.exception.code, "clip_too_long")

    def test_game_clip_provenance_and_member_upload_label(self):
        game = self._ready_game()
        clip = self.net.create_clip_definition(self.member, {
            "source_game_id": game["game_id"], "start_seconds": 0, "end_seconds": 20,
        })
        self.net.render_clip(self.member, clip["clip_id"])
        post = self.net.publish_clip(self.member, clip["clip_id"], {
            "caption": "Lincoln dunk", "visibility": "private",
        })
        self.assertEqual(post["provenance"]["label"], "Three-Zone Game Clip")
        self.assertEqual(post["watch_full_game"]["label"], "Watch Full Game")
        self.assertTrue(post.get("derived_media_asset_id") or post.get("media_asset_id"))
        upload = self.net.create_upload(self.member, {"kind": "photo"})
        token = upload["upload_url"].rsplit("/", 1)[-1]
        self.net.complete_fake_upload(token, {"duration_seconds": 0})
        job = self.cp.db.query_one(
            "SELECT * FROM upload_jobs WHERE upload_job_id=?", (upload["upload_job_id"],)
        )
        asset = self.cp.db.query_one(
            "SELECT media_asset_id FROM media_assets WHERE provider_uid=?", (job["provider_uid"],)
        )
        member_post = self.net.create_post(self.member, {
            "media_asset_id": asset["media_asset_id"], "caption": "Sideline photo",
            "sport": "basketball", "visibility": "public",
        })
        self.assertEqual(member_post["provenance"]["label"], "Member Upload")

    def test_private_game_hidden_from_other_member(self):
        game = self._ready_game()
        with self.assertRaises(ForbiddenError):
            self.net.game_view(self.other, game["game_id"])

    def test_revoked_rights_block_playback_and_derived_publish(self):
        game = self._ready_game(event_id="evt_mw_wrestling")
        clip = self.net.create_clip_definition(self.member, {
            "source_game_id": game["game_id"], "start_seconds": 0, "end_seconds": 20,
        })
        self.net.render_clip(self.member, clip["clip_id"])
        self.cp.revoke_rights("evt_mw_wrestling", self.owner, "stop")
        with self.assertRaises(ForbiddenError):
            self.net.game_playback(self.member, game["game_id"])
        with self.assertRaises(ForbiddenError) as ctx:
            self.net.publish_clip(self.member, clip["clip_id"], {"visibility": "public"})
        self.assertEqual(ctx.exception.code, "rights_exceeded")

    def test_clip_render_is_idempotent(self):
        game = self._ready_game()
        clip = self.net.create_clip_definition(self.member, {
            "source_game_id": game["game_id"], "start_seconds": 0, "end_seconds": 20,
        })
        first = self.net.render_clip(self.member, clip["clip_id"])
        second = self.net.render_clip(self.member, clip["clip_id"])
        self.assertEqual(first["clip_id"], second["clip_id"])
        self.assertEqual(first["provider_job_id"], second["provider_job_id"])
        self.assertEqual(first["derived_media_asset_id"], second["derived_media_asset_id"])
        self.assertEqual(len(self.provider.render_jobs), 1)

    def test_idempotency_key_is_per_owner(self):
        first = self.net.create_upload(self.member, {"kind": "photo", "idempotency_key": "shared-key"})
        second = self.net.create_upload(self.member, {"kind": "photo", "idempotency_key": "shared-key"})
        self.assertEqual(first["upload_job_id"], second["upload_job_id"])
        other = self.net.create_upload(self.other, {"kind": "photo", "idempotency_key": "shared-key"})
        self.assertNotEqual(other["upload_job_id"], first["upload_job_id"])

    def test_photo_upload_uses_photo_store_not_stream(self):
        contract = self.net.create_upload(self.member, {"kind": "photo"})
        self.assertEqual(contract["upload_method"], "put")
        self.assertTrue(contract["upload_url"].startswith("https://photos.test/"))
        self.assertNotIn("videodelivery", contract["upload_url"])
        self.assertNotIn("cloudflare", contract["upload_url"].lower())
        self.assertNotIn("/api/network", contract["upload_url"])
        blob = str(contract)
        self.assertNotIn("api_token", blob)
        with self.assertRaises(Exception):
            self.provider.create_direct_upload("photo")


class VisibilityAndFeedTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.other = self.cp.register_viewer("jordanf", "password123", "Jordan")["user"]
        self.worker = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")

    def _public_photo(self, user, caption="Hello", visibility="public", sport="basketball"):
        upload = self.net.create_upload(user, {"kind": "photo"})
        self.net.complete_fake_upload(upload["upload_url"].rsplit("/", 1)[-1], {})
        job = self.cp.db.query_one(
            "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?", (upload["upload_job_id"],)
        )
        asset = self.cp.db.query_one(
            "SELECT media_asset_id FROM media_assets WHERE provider_uid=?", (job["provider_uid"],)
        )
        return self.net.create_post(user, {
            "media_asset_id": asset["media_asset_id"], "caption": caption,
            "sport": sport, "visibility": visibility,
        })

    def test_public_private_team_authorization(self):
        public = self._public_photo(self.member, "Public hoop")
        self.assertEqual(self.net.post_view(None, public["post_id"])["post_id"], public["post_id"])
        private = self._public_photo(self.member, "Private hoop", visibility="private")
        self.net.post_view(self.member, private["post_id"])
        with self.assertRaises(ForbiddenError):
            self.net.post_view(self.other, private["post_id"])
        team = self._public_photo(self.member, "Team only", visibility="team")
        with self.assertRaises(ForbiddenError):
            self.net.post_view(self.other, team["post_id"])

    def test_feed_modes_filters_cursors_no_dupes(self):
        self._public_photo(self.member, "One", sport="basketball")
        self._public_photo(self.member, "Two", sport="soccer")
        self.net.follow(self.other, "demo_viewer")
        feed = self.net.feed(self.other, "for_you")
        ids = [i["post_id"] for i in feed["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        soccer = self.net.feed(self.other, "for_you", sport="soccer")
        self.assertTrue(all(i["sport"] == "soccer" for i in soccer["items"]))
        following = self.net.feed(self.other, "following")
        self.assertGreaterEqual(len(following["items"]), 1)
        local = self.net.feed(self.other, "local")
        self.assertGreaterEqual(len(local["items"]), 1)
        page = self.net.feed(self.other, "for_you", limit=1)
        self.assertEqual(len(page["items"]), 1)
        nxt = self.net.feed(self.other, "for_you", cursor=page["cursor"], limit=1)
        if nxt["items"]:
            self.assertNotEqual(nxt["items"][0]["post_id"], page["items"][0]["post_id"])

    def test_athlete_tags_from_handles(self):
        other_profile = self.net.ensure_profile(self.other)
        upload = self.net.create_upload(self.member, {"kind": "photo"})
        self.net.complete_fake_upload(upload["upload_url"].rsplit("/", 1)[-1], {})
        job = self.cp.db.query_one(
            "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?", (upload["upload_job_id"],)
        )
        asset = self.cp.db.query_one(
            "SELECT media_asset_id FROM media_assets WHERE provider_uid=?", (job["provider_uid"],)
        )
        post = self.net.create_post(self.member, {
            "media_asset_id": asset["media_asset_id"], "caption": "Tagged play",
            "sport": "basketball", "visibility": "public",
            "tagged_handles": [other_profile["handle"]],
            "tagged_team_ids": ["team_lincoln"],
        })
        self.assertEqual(post["athlete_tags"][0]["handle"], other_profile["handle"])
        self.assertNotIn("user_id", post["athlete_tags"][0])
        self.assertIn("team_lincoln", post["team_tags"])
        self.assertNotIn("user_id", post)


class SocialAndModerationTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.other = self.cp.register_viewer("caseyfan", "password123", "Casey")["user"]
        self.worker = self.cp.get_user("demo-worker")
        self.owner = self.cp.get_user("demo-owner")

    def _post(self):
        upload = self.net.create_upload(self.member, {"kind": "photo"})
        self.net.complete_fake_upload(upload["upload_url"].rsplit("/", 1)[-1], {})
        job = self.cp.db.query_one(
            "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?", (upload["upload_job_id"],)
        )
        asset = self.cp.db.query_one(
            "SELECT media_asset_id FROM media_assets WHERE provider_uid=?", (job["provider_uid"],)
        )
        return self.net.create_post(self.member, {
            "media_asset_id": asset["media_asset_id"], "caption": "Game day",
            "sport": "football", "visibility": "public",
        })

    def test_like_save_follow_idempotent(self):
        post = self._post()
        a = self.net.react(self.other, "post", post["post_id"])
        b = self.net.react(self.other, "post", post["post_id"])
        self.assertEqual(a["like_count"], b["like_count"])
        self.net.save_item(self.other, "post", post["post_id"])
        self.net.save_item(self.other, "post", post["post_id"])
        saves = self.cp.db.query(
            "SELECT * FROM saves WHERE subject_id=?", (post["post_id"],)
        )
        self.assertEqual(len(saves), 1)
        self.net.follow(self.other, "demo_viewer")
        self.net.follow(self.other, "demo_viewer")
        follows = self.cp.db.query("SELECT * FROM follows")
        self.assertEqual(len(follows), 1)

    def test_comment_ownership_and_report(self):
        post = self._post()
        comment = self.net.add_comment(self.other, "post", post["post_id"], "Nice play")
        stranger = self.cp.register_viewer("stranger1", "password123", "Stranger")["user"]
        with self.assertRaises(ForbiddenError):
            self.net.delete_comment(stranger, comment["comment_id"])
        self.net.delete_comment(self.other, comment["comment_id"])
        self.net.report(self.other, {"subject_type": "post", "subject_id": post["post_id"], "reason": "not sports"})
        cases = self.cp.db.query("SELECT * FROM moderation_cases WHERE subject_id=?", (post["post_id"],))
        self.assertTrue(cases)
        self.assertIsNone(cases[0]["policy_decision"])

    def test_inbox_authorization(self):
        post = self._post()
        share = self.net.send_media(self.member, {
            "subject_type": "post", "subject_id": post["post_id"],
            "recipient_handle": self.net.ensure_profile(self.other)["handle"],
            "message": "watch this", "idempotency_key": "share-1",
        })
        dup = self.net.send_media(self.member, {
            "subject_type": "post", "subject_id": post["post_id"],
            "recipient_handle": self.net.ensure_profile(self.other)["handle"],
            "idempotency_key": "share-1",
        })
        self.assertTrue(dup["duplicate"])
        inbox = self.net.inbox(self.other)
        self.assertEqual(inbox["items"][0]["share_id"], share["share_id"])
        with self.assertRaises(ForbiddenError):
            self.net.mark_share_read(self.member, share["share_id"])

    def test_classifier_cannot_silently_remove(self):
        post = self._post()
        self.assertEqual(post["publication_status"], "published")
        queue = self.net.review_queue(self.worker)
        self.assertIn("cases", queue)
        if queue["cases"]:
            case = queue["cases"][0]
            self.assertIsNone(case["policy_decision"])
            self.net.decide_moderation(self.worker, case["case_id"], "remove", "not sports")
            removed = self.cp.db.query_one("SELECT publication_status FROM posts WHERE post_id=?",
                                           (case["subject_id"],))
            if removed:
                self.assertEqual(removed["publication_status"], "removed")

    def test_restricted_post_content_state(self):
        post = self._post()
        self.net.report(self.other, {
            "subject_type": "post", "subject_id": post["post_id"], "reason": "rights",
        })
        case = self.cp.db.query_one(
            "SELECT * FROM moderation_cases WHERE subject_id=?", (post["post_id"],)
        )
        self.net.decide_moderation(self.worker, case["case_id"], "restrict", "rights hold")
        view = self.net.post_view(self.member, post["post_id"])
        self.assertEqual(view["publication_status"], "restricted")
        self.assertEqual(view["content_state"], "restricted")
        with self.assertRaises(ForbiddenError):
            self.net.post_view(self.other, post["post_id"])

    def test_worker_versus_owner(self):
        with self.assertRaises(ForbiddenError):
            self.net.evidence_bundle(self.worker, "post", "pst_x")
        with self.assertRaises(ForbiddenError):
            self.net.review_queue(self.member)
        self.net.review_queue(self.worker)
        self.net.review_queue(self.owner)

    def test_audit_and_evidence_export(self):
        post = self._post()
        bundle = self.net.evidence_bundle(self.owner, "post", post["post_id"])
        self.assertTrue(bundle["bundle_hash"].startswith("sha256:"))
        self.assertTrue(any(a["event_type"] == "POST_PUBLISHED" for a in bundle["audit"]))
        csv_text = self.net.evidence_csv(self.owner, "post", post["post_id"])
        self.assertIn("event_type", csv_text)
        html_text = self.net.evidence_html(self.owner, "post", post["post_id"])
        self.assertIn("<table", html_text)
        outbox = self.cp.db.query("SELECT * FROM socket_outbox WHERE type LIKE 'network.%'")
        self.assertTrue(outbox)

    def test_no_stories_routes_tables_or_ui(self):
        tables = {r[0] for r in self.cp.db.query(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertTrue(all("stories" not in name.lower() for name in tables))
        paths = " ".join(r["path"] for r in SITE_ROUTES).lower()
        self.assertNotIn("stories", paths)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("index.html", "portal.js", "ops.html", "app.js"):
            with open(os.path.join(root, "backend", "static", name), encoding="utf-8") as handle:
                self.assertNotIn("Stories", handle.read())


class FakeProviderE2ETests(unittest.TestCase):
    def test_member_game_clip_feed_loop(self):
        cp, portal, net, provider = build_net()
        created = cp.register_viewer("clipper1", "password123", "Clipper")
        user = created["user"]
        game = net.submit_game(user, {
            "sport": "basketball", "home_team_name": "Lincoln", "away_team_name": "West",
            "rights_attestation": True, "level": "high_school",
        })
        net.complete_fake_upload(game["upload"]["upload_url"].rsplit("/", 1)[-1],
                                 {"duration_seconds": 400})
        ready = net.game_view(user, game["game_id"])
        self.assertEqual(ready["processing_status"], "ready")
        clip = net.create_clip_definition(user, {
            "source_game_id": game["game_id"], "start_seconds": 40, "end_seconds": 60,
        })
        net.render_clip(user, clip["clip_id"])
        post = net.publish_clip(user, clip["clip_id"], {
            "caption": "Fourth quarter run", "visibility": "private",
        })
        self.assertEqual(post["provenance"]["label"], "Three-Zone Game Clip")
        feed = net.feed(user, "for_you")
        self.assertTrue(any(i["post_id"] == post["post_id"] for i in feed["items"]))
        opened = net.game_view(user, game["game_id"])
        self.assertEqual(opened["source_media_asset_id"], ready["source_media_asset_id"])
        self.assertIsNotNone(build_provider(cp.config))


if __name__ == "__main__":
    unittest.main(verbosity=2)
