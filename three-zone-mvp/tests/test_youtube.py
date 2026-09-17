"""YouTube URL parsing and Huddle YouTube clip posts."""

from __future__ import annotations

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import urllib.error
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

    def test_empty_youtube_url_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self.net.create_post(self.member, {
                "youtube_url": "",
                "caption": "blank clip",
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
        with self.assertRaises(ValidationError) as ctx:
            self.net.decide_post(self.worker, post["post_id"], "restore", "already live")
        self.assertEqual(ctx.exception.code, "bad_status")
        self.cp.db.execute(
            "UPDATE posts SET publication_status='processing' WHERE post_id=?",
            (post["post_id"],),
        )
        with self.assertRaises(ValidationError) as ctx:
            self.net.decide_post(self.worker, post["post_id"], "restrict", "too soon")
        self.assertEqual(ctx.exception.code, "bad_status")

    def test_seeded_kc_youtube_clips_and_teams(self):
        from backend.http_server import _routes
        feed = self.net.feed(self.member, "for_you")
        yt = [i for i in feed["items"] if i.get("media") and i["media"].get("kind") == "youtube"]
        self.assertGreaterEqual(len(yt), 4)
        sports = {i["sport"] for i in yt}
        self.assertTrue({"basketball", "football", "soccer", "baseball", "volleyball"} <= sports)
        baseball = next(i for i in yt if i["post_id"] == "pst_kc_baseball")
        self.assertEqual(baseball["sport"], "baseball")
        self.assertIn("Baseball", baseball["caption"])
        self.assertTrue(any("Kansas City" in (i["caption"] or "") for i in yt))
        self.assertTrue(all((i.get("media") or {}).get("poster_url") for i in yt))
        activity = self.net.friends_activity(self.member)
        self.assertGreaterEqual(len(activity["items"]), 1)
        chris = next(i for i in activity["items"] if i["member_id"] == "demo-chris")
        self.assertEqual(chris["event_id"], "evt_kc_live_bball")
        self.assertEqual(chris["activity"], "watching_live")
        teams = self.net.list_member_teams(self.member)
        ids = {t["team_id"] for t in teams["teams"]}
        self.assertIn("team_northview_bball", ids)
        queue = self.net.review_queue(self.worker)
        self.assertTrue(any(p.get("media", {}).get("kind") == "youtube" for p in queue["posts"]))
        post_pat = next(p for _m, p, h, _a in _routes() if h == "h_net_post_update")
        review_pat = next(p for _m, p, h, _a in _routes() if h == "h_net_review_post")
        comment_pat = next(p for _m, p, h, _a in _routes() if h == "h_net_comment_delete")
        media_pat = next(p for _m, p, h, _a in _routes() if h == "h_net_media")
        like_pat = next(p for _m, p, h, _a in _routes() if h == "h_member_post_like")
        self.assertTrue(post_pat.match("/api/network/posts/pst_kc_poster"))
        self.assertTrue(review_pat.match("/api/network/review/posts/pst_kc_poster"))
        self.assertTrue(comment_pat.match("/api/network/comments/cmt_kc_maya/delete"))
        self.assertTrue(media_pat.match("/api/network/media/med_yt_kc_poster"))
        self.assertTrue(like_pat.match("/api/member/posts/pst_kc_poster/like"))


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


class SeededPostHttpTests(unittest.TestCase):
    def setUp(self):
        cp, _portal, net, provider = build_net()
        self.cp = cp
        self.net = net
        self.httpd = make_http_server(
            replace(cp.config, http_port=0), cp, "/tmp",
            provider=provider, photo_storage=net.photo_storage,
        )
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _login(self, username, password):
        req = urllib.request.Request(
            self.base + "/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.headers.get("Set-Cookie") or ""
        for part in raw.split(";"):
            piece = part.strip()
            if piece.startswith("tz_member_session="):
                return piece.split("=", 1)[1]
        self.fail("login did not set tz_member_session")

    def _json(self, method, path, body=None, cookie=None):
        headers = {}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if cookie:
            headers["Cookie"] = f"tz_member_session={cookie}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def test_seeded_poster_edit_review_and_comment_routes(self):
        from backend.config import DEMO_SEED_PASSWORDS
        viewer = self._login("demo-viewer", DEMO_SEED_PASSWORDS["demo-viewer"])
        worker = self._login("demo-worker", DEMO_SEED_PASSWORDS["demo-worker"])
        maya = self._login("demo-maya", DEMO_SEED_PASSWORDS["demo-viewer"])

        status, body = self._json("GET", "/api/network/posts/pst_kc_poster", cookie=viewer)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["post"]["post_id"], "pst_kc_poster")
        self.assertEqual(body["post"]["media"]["kind"], "youtube")

        status, updated = self._json("POST", "/api/network/posts/pst_kc_poster", {
            "caption": "Andre's poster — Kansas City night.",
        }, cookie=viewer)
        self.assertEqual(status, 200, updated)
        self.assertIn("Kansas City", updated["post"]["caption"])

        status, liked = self._json("POST", "/api/member/posts/pst_kc_poster/like", {}, cookie=viewer)
        self.assertEqual(status, 200, liked)

        status, restricted = self._json("POST", "/api/network/review/posts/pst_kc_poster", {
            "action": "restrict", "reason": "ops review",
        }, cookie=worker)
        self.assertEqual(status, 200, restricted)
        self.assertEqual(restricted["post"]["publication_status"], "restricted")

        status, restored = self._json("POST", "/api/network/review/posts/pst_kc_poster", {
            "action": "restore", "reason": "cleared",
        }, cookie=worker)
        self.assertEqual(status, 200, restored)
        self.assertEqual(restored["post"]["publication_status"], "published")

        status, deleted = self._json(
            "POST", "/api/network/comments/cmt_kc_maya/delete", {}, cookie=maya,
        )
        self.assertEqual(status, 200, deleted)
        self.assertTrue(deleted.get("ok"))

    def test_empty_youtube_url_is_http_400(self):
        from backend.config import DEMO_SEED_PASSWORDS
        viewer = self._login("demo-viewer", DEMO_SEED_PASSWORDS["demo-viewer"])
        status, body = self._json("POST", "/api/network/posts", {
            "youtube_url": "",
            "caption": "blank clip",
            "sport": "basketball",
        }, cookie=viewer)
        self.assertEqual(status, 400, body)
        self.assertEqual(body.get("code"), "bad_youtube")


if __name__ == "__main__":
    unittest.main(verbosity=2)
