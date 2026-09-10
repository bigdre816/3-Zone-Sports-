"""Huddle runtime: friends, moments, watch parties, ranking, Moten clip evidence."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.control_plane import ForbiddenError
from tests.test_network import build_net


class HuddleFriendsTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.other = self.cp.register_viewer("huddlepal", "password123", "Huddle Pal")["user"]
        self.net.ensure_profile(self.member)
        self.net.ensure_profile(self.other)

    def test_friend_request_accept_and_unfriend(self):
        pending = self.net.request_friend(self.member, "huddlepal")
        self.assertEqual(pending["status"], "pending")
        notes = self.net.list_notifications(self.other)
        self.assertGreaterEqual(notes["unread_count"], 1)
        accepted = self.net.accept_friend(self.other, "andre")
        self.assertEqual(accepted["status"], "accepted")
        self.assertIn(
            self.net.ensure_profile(self.other)["profile_id"],
            self.net._friend_ids(self.net.ensure_profile(self.member)["profile_id"]),
        )
        gone = self.net.unfriend(self.member, "huddlepal")
        self.assertEqual(gone["status"], "none")

    def test_watching_activity_requires_opt_in(self):
        self.net.request_friend(self.member, "huddlepal")
        self.net.accept_friend(self.other, "andre")
        hidden = self.net.friends_activity(self.other)
        self.assertEqual(hidden["items"], [])
        self.net.update_settings(self.member, {"show_watching_to_friends": True})
        self.cp.db.execute(
            "INSERT INTO view_sessions(session_id,event_id,user_id,pseudonym,lease_id,rights_id,"
            "rights_version,started_at,ended_at,last_seq,last_heartbeat_at,qualified_seconds,"
            "state,close_reason,digest,canonical_json,property_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("VS-TEST1", "evt_mw_basketball", self.member["user_id"], "fan", "lease_x",
             None, 1, 1.0, None, 0, 1.0, 0, "open", None, None, None, None),
        )
        shown = self.net.friends_activity(self.other)
        self.assertEqual(len(shown["items"]), 1)
        self.assertEqual(shown["items"][0]["activity"], "watching_live")

    def test_block_stops_friend_request(self):
        self.net.block_member(self.other, "andre")
        with self.assertRaises(ForbiddenError) as ctx:
            self.net.request_friend(self.member, "huddlepal")
        self.assertEqual(ctx.exception.code, "blocked")


class HuddleMomentsAndStudioTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.owner = self.cp.get_user("demo-owner")

    def test_scoreboard_emits_publishable_moment(self):
        first = self.net.ingest_score_moment("evt_mw_basketball", {"home": 2, "away": 0, "clock": "7:40"})
        self.assertIsNotNone(first)
        self.assertEqual(first["status"], "publishable")
        listed = self.net.list_event_moments(self.member, "evt_mw_basketball")
        self.assertEqual(listed["moments"][0]["type"], "score")
        timeline = self.net.event_timeline(self.member, "evt_mw_basketball")
        self.assertTrue(timeline["moments"])
        noop = self.net.ingest_score_moment(
            "evt_mw_basketball",
            {"home": 2, "away": 0, "clock": "7:40"},
            {"home": 2, "away": 0, "clock": "7:40"},
        )
        self.assertIsNone(noop)

    def test_studio_sources_are_entitled_games(self):
        sources = self.net.studio_sources(self.member)
        self.assertIn("games", sources)
        self.assertIn("events", sources)


class HuddleWatchPartyTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.other = self.cp.register_viewer("partyguest", "password123", "Guest")["user"]
        self.net.ensure_profile(self.member)
        self.net.ensure_profile(self.other)

    def test_friends_party_join_and_social_message(self):
        self.net.request_friend(self.member, "partyguest")
        self.net.accept_friend(self.other, "andre")
        party = self.net.create_watch_party(self.member, {"event_id": "evt_mw_basketball"})
        joined = self.net.join_watch_party(self.other, party["party_id"])
        self.assertTrue(joined["ok"])
        msg = self.net.post_watch_party_message(self.other, party["party_id"], {
            "kind": "comment", "body": "nice run",
        })
        self.assertEqual(msg["kind"], "comment")
        view = self.net.watch_party_view(self.member, party["party_id"])
        self.assertEqual(len(view["members"]), 2)

    def test_stranger_cannot_join_friends_party(self):
        party = self.net.create_watch_party(self.member, {"event_id": "evt_mw_basketball"})
        with self.assertRaises(ForbiddenError):
            self.net.join_watch_party(self.other, party["party_id"])


class HuddleFeedRankingAndShareTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.other = self.cp.register_viewer("rankfan", "password123", "Rank Fan")["user"]
        self.stranger = self.cp.register_viewer("stranger1", "password123", "Stranger")["user"]
        self.owner = self.cp.get_user("demo-owner")

    def _photo(self, user, caption):
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
            "sport": "basketball", "visibility": "public",
        })

    def test_zone_alias_and_follow_ranks_higher(self):
        followed = self._photo(self.member, "Lincoln hoop")
        other = self._photo(self.stranger, "Random hoop")
        self.net.follow(self.other, "andre")
        zone = self.net.feed(self.other, "zone")
        self.assertEqual(zone["mode"], "zone")
        self.assertTrue(any(i["post_id"] == followed["post_id"] for i in zone["items"]))
        ranked = self.net.feed(self.other, "for_you")
        self.assertEqual(ranked["ranking"], "sports-relevance")
        ids = [i["post_id"] for i in ranked["items"]]
        self.assertLess(ids.index(followed["post_id"]), ids.index(other["post_id"]))

    def test_copy_link_share(self):
        post = self._photo(self.member, "Share this")
        shared = self.net.copy_link_share(self.member, post["post_id"], "copy_link")
        self.assertEqual(shared["destination"], "copy_link")
        self.assertIn("/post/", shared["url"])
        with self.assertRaises(ForbiddenError):
            self.net.copy_link_share(self.member, post["post_id"], "instagram")


class HuddleRightsAndMotenTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.owner = self.cp.get_user("demo-owner")

    def test_revoke_marks_feed_unavailable_and_queues_moten(self):
        game = self.net.submit_game(self.member, {
            "sport": "basketball",
            "home_team_name": "Lincoln",
            "away_team_name": "Central",
            "rights_attestation": True,
            "event_id": "evt_mw_basketball",
            "level": "high_school",
        })
        token = game["upload"]["upload_url"].rsplit("/", 1)[-1]
        self.net.complete_fake_upload(token, {"duration_seconds": 600})
        ready = self.net.game_view(self.member, game["game_id"])
        clip = self.net.create_clip_definition(self.member, {
            "source_game_id": ready["game_id"], "start_seconds": 10, "end_seconds": 30,
        })
        self.net.render_clip(self.member, clip["clip_id"])
        post = self.net.publish_clip(self.member, clip["clip_id"], {
            "caption": "Lincoln dunk", "visibility": "private",
        })
        published = self.cp.db.query_one(
            "SELECT * FROM moten_outbox WHERE handoff_type='clip-published' ORDER BY created_at DESC"
        )
        self.assertIsNotNone(published)
        self.assertEqual(published["source_object_id"], clip["clip_id"])
        self.cp.revoke_rights("evt_mw_basketball", self.owner, "test hold")
        withdrawn = self.net.restrict_derived_from_event("evt_mw_basketball", self.owner)
        self.assertIn(clip["clip_id"], withdrawn["clips"])
        card = self.net.post_view(self.member, post["post_id"])
        self.assertEqual(card["content_state"], "unavailable")
        self.assertIsNone(card.get("media"))
        self.assertIn("no longer available", card["watch_full_game"]["label"])
        moment = self.net.public_moment(self.member, clip["clip_id"])
        self.assertFalse(moment["available"])
        self.assertIsNone(moment["media_url"])
        row = self.cp.db.query_one(
            "SELECT * FROM moten_outbox WHERE handoff_type='clip-withdrawn' ORDER BY created_at DESC"
        )
        self.assertIsNotNone(row)

    def test_parent_comment(self):
        upload = self.net.create_upload(self.member, {"kind": "photo"})
        self.net.complete_fake_upload(upload["upload_url"].rsplit("/", 1)[-1], {})
        job = self.cp.db.query_one(
            "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?", (upload["upload_job_id"],)
        )
        asset = self.cp.db.query_one(
            "SELECT media_asset_id FROM media_assets WHERE provider_uid=?", (job["provider_uid"],)
        )
        post = self.net.create_post(self.member, {
            "media_asset_id": asset["media_asset_id"], "caption": "Talk",
            "sport": "basketball", "visibility": "public",
        })
        parent = self.net.add_comment(self.member, "post", post["post_id"], "first")
        reply = self.net.add_comment(
            self.member, "post", post["post_id"], "second", parent["comment_id"],
        )
        self.assertEqual(reply["parent_comment_id"], parent["comment_id"])


class HuddleShellTests(unittest.TestCase):
    def test_member_chrome_has_huddle_nav_and_cookie_client(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static = os.path.join(root, "backend", "static")
        with open(os.path.join(static, "index.html"), encoding="utf-8") as handle:
            html = handle.read()
        for needle in ("THREEZONE.", "Huddle", "In your zone", "Post to Huddle",
                       "GOOD TO HAVE YOU COURTSIDE", "id=\"bottom-nav\"", "/api.js"):
            self.assertIn(needle, html)
        self.assertNotIn("Stories", html)
        with open(os.path.join(static, "api.js"), encoding="utf-8") as handle:
            api = handle.read()
        self.assertIn('credentials: "include"', api)
        self.assertNotIn("sessionStorage", api)
        with open(os.path.join(static, "portal.js"), encoding="utf-8") as handle:
            js = handle.read()
        self.assertNotIn(" sessionStorage", js)
        self.assertIn("This moment is no longer available.", js)
        self.assertIn("function courtsideGreeting", js)
        self.assertIn("BANNED_GREETING", js)

    def test_member_home_copy_never_says_demo(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static = os.path.join(root, "backend", "static")
        with open(os.path.join(static, "index.html"), encoding="utf-8") as handle:
            html = handle.read()
        self.assertNotIn("demo", html.lower())
        self.assertNotIn("sample content", html.lower())
        self.assertNotIn("interactive preview", html.lower())
        self.assertNotIn("this is a demo", html.lower())


class HuddleGreetingTests(unittest.TestCase):
    def test_seeded_member_is_andre_not_demo(self):
        from backend.identity import greeting_name, public_handle
        from backend.seed import seed_if_empty
        from backend.db import Database

        db = Database(":memory:")
        seed_if_empty(db)
        user = db.query_one("SELECT * FROM users WHERE user_id=?", ("demo-viewer",))
        profile = db.query_one("SELECT * FROM profiles WHERE user_id=?", ("demo-viewer",))
        self.assertEqual(user["display_name"], "Andre")
        self.assertEqual(profile["display_name"], "Andre")
        self.assertEqual(profile["handle"], "andre")
        self.assertEqual(greeting_name(user["display_name"]), "Andre")
        self.assertEqual(public_handle(profile["handle"]), "andre")

    def test_greeting_drops_demo_and_sample_labels(self):
        from backend.identity import greeting_name, public_handle
        self.assertEqual(greeting_name("Demo Member (viewer)"), "")
        self.assertEqual(greeting_name("Sample Content"), "")
        self.assertEqual(greeting_name("Andre Moten"), "Andre")
        self.assertEqual(public_handle("demo_viewer"), "")
        self.assertEqual(public_handle("andre"), "andre")

    def test_existing_database_loses_demo_public_names(self):
        from backend.db import Database
        from backend.seed import seed_if_empty

        db = Database(":memory:")
        seed_if_empty(db)
        db.execute(
            "UPDATE users SET display_name=? WHERE user_id=?",
            ("Demo Member (viewer)", "demo-viewer"),
        )
        db.execute(
            "UPDATE profiles SET display_name=?, handle=? WHERE user_id=?",
            ("Demo Member (viewer)", "demo_viewer", "demo-viewer"),
        )
        seed_if_empty(db)
        user = db.query_one("SELECT * FROM users WHERE user_id=?", ("demo-viewer",))
        profile = db.query_one("SELECT * FROM profiles WHERE user_id=?", ("demo-viewer",))
        self.assertEqual(user["display_name"], "Andre")
        self.assertEqual(profile["display_name"], "Andre")
        self.assertEqual(profile["handle"], "andre")


if __name__ == "__main__":
    unittest.main(verbosity=2)
