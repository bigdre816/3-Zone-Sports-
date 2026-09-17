"""YouTube URL parsing and Huddle YouTube clip posts."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import urllib.request
from dataclasses import replace

from backend.control_plane import ForbiddenError, ValidationError
from backend.http_server import make_http_server
from backend.youtube import parse_youtube_id, youtube_embed_url, youtube_poster_url
from tests.test_network import build_net


class YoutubeParseTests(unittest.TestCase):
    def test_watch_embed_shorts_and_short_links(self):
        vid = "M7lc1UVf-VE"
        self.assertEqual(parse_youtube_id(f"https://www.youtube.com/watch?v={vid}"), vid)
        self.assertEqual(parse_youtube_id(f"https://youtu.be/{vid}"), vid)
        self.assertEqual(parse_youtube_id(f"https://www.youtube.com/embed/{vid}"), vid)
        self.assertEqual(parse_youtube_id(f"https://www.youtube.com/shorts/{vid}"), vid)
        self.assertEqual(parse_youtube_id(vid), vid)
        self.assertIsNone(parse_youtube_id("https://example.com/watch?v=nope"))
        self.assertIn("youtube-nocookie.com/embed/" + vid, youtube_embed_url(vid))
        self.assertIn("/hqdefault.jpg", youtube_poster_url(vid))


class YoutubePostTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider = build_net()
        self.member = self.cp.get_user("demo-viewer")
        self.other = self.cp.register_viewer("ytfan", "password123", "YT Fan")["user"]
        self.worker = self.cp.get_user("demo-worker")
        self.net.ensure_profile(self.member)
        self.net.ensure_profile(self.other)

    def test_member_posts_youtube_and_feed_embeds(self):
        post = self.net.create_post(self.member, {
            "youtube_url": "https://youtu.be/M7lc1UVf-VE",
            "caption": "Kansas City basketball clip",
            "sport": "basketball",
            "visibility": "public",
        })
        self.assertEqual(post["media"]["kind"], "youtube")
        self.assertEqual(post["media"]["youtube_id"], "M7lc1UVf-VE")
        self.assertIn("youtube-nocookie.com/embed/M7lc1UVf-VE", post["media"]["playback_url"])
        self.assertTrue(post["viewer_is_author"])
        feed = self.net.feed(self.other, "for_you")
        match = next(i for i in feed["items"] if i["post_id"] == post["post_id"])
        self.assertEqual(match["media"]["kind"], "youtube")

    def test_bad_youtube_url_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.net.create_post(self.member, {
                "youtube_url": "https://vimeo.com/123",
                "caption": "nope",
                "sport": "basketball",
            })
        self.assertEqual(ctx.exception.code, "bad_youtube")

    def test_member_edits_and_operator_restricts(self):
        post = self.net.create_post(self.member, {
            "youtube_id": "jNQXAC9IVRw",
            "caption": "before",
            "sport": "soccer",
        })
        updated = self.net.update_post(self.member, post["post_id"], {
            "caption": "after", "visibility": "connections",
        })
        self.assertEqual(updated["caption"], "after")
        self.assertEqual(updated["visibility"], "connections")
        with self.assertRaises(ForbiddenError):
            self.net.decide_post(self.member, post["post_id"], "restrict", "no")
        restricted = self.net.decide_post(self.worker, post["post_id"], "restrict", "ops review")
        self.assertEqual(restricted["publication_status"], "restricted")
        restored = self.net.decide_post(self.worker, post["post_id"], "restore", "cleared")
        self.assertEqual(restored["publication_status"], "published")

    def test_seeded_kc_youtube_clips_and_teams(self):
        feed = self.net.feed(self.member, "for_you")
        yt = [i for i in feed["items"] if i.get("media") and i["media"].get("kind") == "youtube"]
        self.assertGreaterEqual(len(yt), 4)
        sports = {i["sport"] for i in yt}
        self.assertTrue({"basketball", "football", "soccer"} <= sports)
        self.assertTrue(any("Kansas City" in (i["caption"] or "") for i in yt))
        self.assertTrue(all((i.get("media") or {}).get("poster_url") for i in yt))
        activity = self.net.friends_activity(self.member)
        self.assertGreaterEqual(len(activity["items"]), 1)
        teams = self.net.list_member_teams(self.member)
        ids = {t["team_id"] for t in teams["teams"]}
        self.assertIn("team_northview_bball", ids)
        queue = self.net.review_queue(self.worker)
        self.assertTrue(any(p.get("media", {}).get("kind") == "youtube" for p in queue["posts"]))


class YoutubeEmbedHeaderTests(unittest.TestCase):
    def test_html_sends_origin_referrer_api_stays_closed(self):
        cp, _portal, net, provider = build_net()
        httpd = make_http_server(
            replace(cp.config, http_port=0), cp, "/tmp",
            provider=provider, photo_storage=net.photo_storage,
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as resp:
                self.assertEqual(
                    resp.headers.get("Referrer-Policy"),
                    "strict-origin-when-cross-origin",
                )
            with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=5) as resp:
                self.assertEqual(resp.headers.get("Referrer-Policy"), "no-referrer")
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
