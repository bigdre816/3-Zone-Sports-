"""BALLDONTLIE adapters, normalization, cache, and public/member score routes."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.control_plane import ControlPlane, SITE_ROUTES
from backend.db import Database
from backend.http_server import make_http_server
from backend.seed import seed_if_empty
from backend.sports_feeds.catalog import match_provider_team, team_by_id
from backend.sports_feeds.client import BalldontlieClient, FeedClientError
from backend.sports_feeds.normalize import chicago_fields, normalize_game, parse_datetime
from backend.sports_feeds.service import GAPS, RIGHTS_NOTE, SportsFeedService

MVP = Path(__file__).resolve().parents[1]
STATIC = MVP / "backend" / "static"

NFL_CHIEFS = {
    "id": 14,
    "conference": "AFC",
    "division": "WEST",
    "location": "Kansas City",
    "name": "Chiefs",
    "full_name": "Kansas City Chiefs",
    "abbreviation": "KC",
}
NFL_RAVENS = {
    "id": 6,
    "conference": "AFC",
    "division": "NORTH",
    "location": "Baltimore",
    "name": "Ravens",
    "full_name": "Baltimore Ravens",
    "abbreviation": "BAL",
}
MLB_ROYALS = {
    "id": 11,
    "slug": "kansas-city-royals",
    "abbreviation": "KC",
    "display_name": "Kansas City Royals",
    "name": "Royals",
    "location": "Kansas City",
}
MLB_YANKEES = {
    "id": 19,
    "abbreviation": "NYY",
    "display_name": "New York Yankees",
    "name": "Yankees",
    "location": "New York",
}
NBA_CELTICS = {
    "id": 2,
    "conference": "East",
    "division": "Atlantic",
    "city": "Boston",
    "name": "Celtics",
    "full_name": "Boston Celtics",
    "abbreviation": "BOS",
}
NBA_LAKERS = {
    "id": 14,
    "conference": "West",
    "division": "Pacific",
    "name": "Lakers",
    "full_name": "Los Angeles Lakers",
    "abbreviation": "LAL",
}

NFL_GAME = {
    "id": 7001,
    "visitor_team": NFL_RAVENS,
    "home_team": NFL_CHIEFS,
    "venue": "GEHA Field at Arrowhead Stadium",
    "week": 1,
    "date": "2024-09-06T00:20:00.000Z",
    "season": 2024,
    "postseason": False,
    "status": "Final",
    "status_state": "final",
    "home_team_score": 27,
    "visitor_team_score": 20,
}
MLB_GAME = {
    "id": 88001,
    "home_team_name": "Kansas City Royals",
    "away_team_name": "New York Yankees",
    "home_team": MLB_ROYALS,
    "away_team": MLB_YANKEES,
    "date": "2024-07-04T18:10:00.000Z",
    "home_team_data": {"hits": 9, "runs": 5, "errors": 0},
    "away_team_data": {"hits": 6, "runs": 3, "errors": 1},
    "venue": "Kauffman Stadium",
    "status": "STATUS_FINAL",
    "status_state": "final",
    "period": 9,
    "clock": 0,
    "display_clock": "0:00",
}
NBA_GAME = {
    "id": 15907925,
    "date": "2025-01-05",
    "season": 2024,
    "status": "4th Qtr",
    "status_state": "in_progress",
    "period": 4,
    "time": "3:44",
    "datetime": "2025-01-05T23:00:00.000Z",
    "home_team_score": 108,
    "visitor_team_score": 101,
    "home_team": NBA_LAKERS,
    "visitor_team": NBA_CELTICS,
}


class FakeClient:
    def __init__(self):
        self.configured = True
        self.calls = []
        self.fail_games = False
        self.nba_prefix = "/nba/v1"
        self.games = {
            "NFL": [NFL_GAME],
            "MLB": [MLB_GAME],
            "NBA": [NBA_GAME],
        }
        self.teams = {
            "NFL": [NFL_CHIEFS, NFL_RAVENS],
            "MLB": [MLB_ROYALS, MLB_YANKEES],
            "NBA": [NBA_CELTICS, NBA_LAKERS],
        }

    def list_teams(self, league):
        self.calls.append(("teams", league))
        return list(self.teams[league])

    def list_games(self, league, *, dates, team_ids=None):
        self.calls.append(("games", league, tuple(dates), tuple(team_ids or ())))
        if self.fail_games:
            raise FeedClientError("timeout", "provider timeout")
        return list(self.games[league])


def _svc(client=None, key=""):
    cfg = Config(env="demo", allowed_origins=["http://127.0.0.1"], balldontlie_api_key=key)
    db = Database(":memory:")
    seed_if_empty(db)
    fake = client if client is not None else FakeClient()
    if key:
        fake.configured = True
    else:
        fake.configured = False
    return SportsFeedService(cfg, db, client=fake, sleeper=lambda _s: None), fake, cfg, db


class NormalizeTests(unittest.TestCase):
    def test_nfl_final_and_catalog_link(self):
        game = normalize_game("NFL", NFL_GAME, retrieved_at=datetime(2026, 9, 18, tzinfo=timezone.utc))
        self.assertEqual(game["provider"], "balldontlie")
        self.assertEqual(game["league"], "NFL")
        self.assertEqual(game["provider_game_id"], "7001")
        self.assertEqual(game["external_game_id"], "bdl:nfl:7001")
        self.assertEqual(game["status"], "final")
        self.assertEqual(game["home"]["team_id"], "team_nfl_kc_chiefs")
        self.assertEqual(game["home"]["score"], 27)
        self.assertEqual(game["away"]["score"], 20)
        self.assertEqual(game["venue"], "GEHA Field at Arrowhead Stadium")
        self.assertEqual(game["timezone"], "America/Chicago")
        self.assertTrue(game["display_local"].endswith("CT"))
        self.assertIsNone(game["inning"])
        self.assertEqual(game["source_ref"], "balldontlie:nfl:7001")

    def test_mlb_uses_runs_and_inning(self):
        game = normalize_game("MLB", MLB_GAME, retrieved_at=datetime(2026, 9, 18, tzinfo=timezone.utc))
        self.assertEqual(game["home"]["team_id"], "team_mlb_kc_royals")
        self.assertEqual(game["home"]["score"], 5)
        self.assertEqual(game["away"]["score"], 3)
        self.assertEqual(game["inning"], 9)
        self.assertIsNone(game["period"])

    def test_nba_in_progress_clock(self):
        game = normalize_game("NBA", NBA_GAME, retrieved_at=datetime(2026, 9, 18, tzinfo=timezone.utc))
        self.assertEqual(game["status"], "in_progress")
        self.assertEqual(game["clock"], "3:44")
        self.assertEqual(game["period"], 4)
        self.assertEqual(game["away"]["team_id"], "team_nba_bos")
        self.assertEqual(game["home"]["team_id"], "team_nba_lal")

    def test_unknown_fields_are_null(self):
        game = normalize_game("NFL", {"id": 1, "status": "???"}, retrieved_at=datetime(2026, 9, 18, tzinfo=timezone.utc))
        self.assertIsNone(game["status"])
        self.assertIsNone(game["home"]["name"])
        self.assertIsNone(game["home"]["score"])
        self.assertIsNone(game["scheduled_start"])
        self.assertIsNone(game["venue"])

    def test_chicago_helper_labels_timezone(self):
        dt = parse_datetime("2024-09-06T00:20:00.000Z")
        fields = chicago_fields(dt)
        self.assertEqual(fields["timezone"], "America/Chicago")
        self.assertTrue(fields["scheduled_start"].endswith("Z"))
        offset = fields["scheduled_start_chicago"]
        self.assertTrue(offset.endswith("-05:00") or offset.endswith("-06:00"), offset)

    def test_match_chiefs_not_royals(self):
        self.assertEqual(match_provider_team("NFL", NFL_CHIEFS).team_id, "team_nfl_kc_chiefs")
        self.assertEqual(match_provider_team("MLB", MLB_ROYALS).team_id, "team_mlb_kc_royals")
        self.assertIsNone(match_provider_team("NFL", MLB_ROYALS))


class FeedServiceTests(unittest.TestCase):
    def test_not_configured_is_fail_closed(self):
        svc, fake, cfg, db = _svc(key="")
        fake.configured = False
        snap = svc.snapshot()
        self.assertEqual(snap["freshness"], "not_configured")
        self.assertEqual(snap["games"], [])
        self.assertEqual(snap["configured"], False)
        self.assertEqual(fake.calls, [])
        self.assertEqual(snap["gaps"]["college"]["status"], "not_configured")
        self.assertEqual(snap["gaps"]["high_school"]["status"], "not_configured")
        self.assertIn("not a streaming entitlement", snap["rights_note"].lower())

    def test_mocked_provider_normalizes_and_prioritizes_kc(self):
        svc, fake, cfg, db = _svc(key="test-key")
        snap = svc.snapshot(sports=["basketball"], followed_team_ids=["team_nba_bos"], refresh=True)
        self.assertEqual(snap["freshness"], "fresh")
        self.assertEqual(len(snap["games"]), 3)
        self.assertEqual(snap["sections"]["local"][0]["home"]["team_id"] in {
            "team_nfl_kc_chiefs", "team_mlb_kc_royals",
        } or snap["sections"]["local"][0]["away"]["team_id"] in {
            "team_nfl_kc_chiefs", "team_mlb_kc_royals",
        }, True)
        self.assertTrue(any(g["league"] == "NFL" for g in snap["sections"]["local"]))
        self.assertTrue(any(g["league"] == "MLB" for g in snap["sections"]["local"]))
        self.assertEqual(snap["sections"]["nba_preferred"][0]["away"]["team_id"], "team_nba_bos")
        self.assertIn("NFL", [c[1] for c in fake.calls if c[0] == "games"])

    def test_failure_does_not_invent_demo_scores(self):
        svc, fake, cfg, db = _svc(key="test-key")
        svc.refresh()
        fake.fail_games = True
        health = svc.refresh()
        snap = svc.snapshot()
        self.assertTrue(len(snap["games"]) >= 1)
        self.assertNotIn(99, [g["home"]["score"] for g in snap["games"]])
        self.assertIn(health["freshness"], ("stale", "fresh", "unavailable"))
        for game in snap["games"]:
            self.assertNotEqual(game["home"]["score"], 999)

    def test_team_page_filters(self):
        svc, fake, cfg, db = _svc(key="test-key")
        snap = svc.snapshot(team_id="team_nfl_kc_chiefs", refresh=True)
        self.assertEqual(snap["bucket"], "team")
        self.assertEqual(snap["team"]["name"], "Kansas City Chiefs")
        self.assertTrue(all(
            (g["home"]["team_id"] == "team_nfl_kc_chiefs") or (g["away"]["team_id"] == "team_nfl_kc_chiefs")
            for g in snap["games"]
        ))

    def test_persists_snapshot(self):
        svc, fake, cfg, db = _svc(key="test-key")
        svc.refresh()
        row = db.query_one("SELECT league, freshness FROM sports_feed_snapshots WHERE league='NFL'")
        self.assertIsNotNone(row)
        self.assertEqual(row["league"], "NFL")


class RateLimitClientTests(unittest.TestCase):
    def test_retry_after_429(self):
        sleeps = []

        class Boom:
            def __init__(self):
                self.n = 0

            def __call__(self, request, timeout=None, context=None):
                self.n += 1
                if self.n == 1:
                    raise urllib.error.HTTPError(
                        "https://api.balldontlie.io/nfl/v1/teams", 429, "rate",
                        {"Retry-After": "0.01"}, None,
                    )
                class Resp:
                    def read(self):
                        return json.dumps({"data": [NFL_CHIEFS], "meta": {}}).encode()
                    def __enter__(self):
                        return self
                    def __exit__(self, *a):
                        return False
                return Resp()

        client = BalldontlieClient("k", sleeper=lambda s: sleeps.append(s), opener=Boom())
        payload = client.get("/nfl/v1/teams")
        self.assertEqual(payload["data"][0]["abbreviation"], "KC")
        self.assertTrue(sleeps)


class HttpRouteTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                          allowed_origins=["http://127.0.0.1"])
        self.db = Database(":memory:")
        seed_if_empty(self.db)
        self.cp = ControlPlane(self.db, self.cfg)
        self.fake = FakeClient()
        self.fake.configured = False
        self.svc = SportsFeedService(self.cfg, self.db, client=self.fake, sleeper=lambda _s: None)
        self.httpd = make_http_server(self.cfg, self.cp, "/tmp", sports_feeds=self.svc, start_feed_poller=False)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _get(self, path, cookie=None):
        req = urllib.request.Request(self.base + path)
        if cookie:
            req.add_header("Cookie", cookie)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    def test_public_scores_not_configured(self):
        payload = self._get("/api/public/scores")
        self.assertEqual(payload["freshness"], "not_configured")
        self.assertEqual(payload["games"], [])
        self.assertEqual(payload["gaps"]["college"], GAPS["college"])
        upcoming = self._get("/api/public/scores/upcoming")
        self.assertEqual(upcoming["bucket"], "upcoming")
        team = self._get("/api/public/scores/teams/team_nfl_kc_chiefs")
        self.assertEqual(team["team"]["team_id"], "team_nfl_kc_chiefs")

    def test_health_includes_feeds_without_secrets(self):
        payload = self._get("/api/health")
        self.assertEqual(payload["status"], "ok")
        blob = json.dumps(payload)
        self.assertNotIn("test-key", blob)
        self.assertNotIn("Authorization", blob)
        self.assertIn("sports_feeds", payload)
        self.assertEqual(payload["sports_feeds"]["freshness"], "not_configured")

    def test_member_scores_and_browser_never_calls_provider(self):
        login = urllib.request.Request(
            self.base + "/api/auth/login",
            data=json.dumps({"username": "demo-viewer", "password": "change-me-viewer-local"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(login, timeout=5) as resp:
            cookie = resp.headers.get("Set-Cookie")
        payload = self._get("/api/member/scores", cookie=cookie.split(";")[0])
        self.assertIn("my_zone", payload)
        self.assertIn("local", payload["my_zone"])
        portal = (STATIC / "portal.js").read_text(encoding="utf-8")
        api_js = (STATIC / "api.js").read_text(encoding="utf-8")
        self.assertNotIn("balldontlie.io", portal)
        self.assertNotIn("balldontlie.io", api_js)
        self.assertIn("/api/member/scores", portal)
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("id=\"view-scores\"", html)
        self.assertIn("id=\"view-team\"", html)

    def test_mocked_http_scores_when_configured(self):
        cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                     allowed_origins=["http://127.0.0.1"], balldontlie_api_key="k")
        db = Database(":memory:")
        seed_if_empty(db)
        cp = ControlPlane(db, cfg)
        fake = FakeClient()
        svc = SportsFeedService(cfg, db, client=fake, sleeper=lambda _s: None)
        httpd = make_http_server(cfg, cp, "/tmp", sports_feeds=svc, start_feed_poller=False)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            with urllib.request.urlopen(f"http://{host}:{port}/api/public/scores", timeout=5) as resp:
                payload = json.loads(resp.read())
            self.assertEqual(payload["configured"], True)
            self.assertGreaterEqual(len(payload["games"]), 1)
            self.assertTrue(any(g["league"] == "NFL" for g in payload["games"]))
            finals = json.loads(urllib.request.urlopen(f"http://{host}:{port}/api/public/scores/finals", timeout=5).read())
            self.assertEqual(finals["bucket"], "finals")
        finally:
            httpd.shutdown()
            httpd.server_close()


class CatalogAndDocsTests(unittest.TestCase):
    def test_routes_and_example_env(self):
        paths = {r["path"] for r in SITE_ROUTES}
        self.assertIn("/api/public/scores", paths)
        self.assertIn("/api/member/scores", paths)
        env = (MVP / "config.example.env").read_text(encoding="utf-8")
        self.assertIn("BALLDONTLIE_API_KEY=", env)
        self.assertNotRegex(env, r"BALLDONTLIE_API_KEY=.+")
        self.assertEqual(team_by_id("team_nfl_kc_chiefs").market, "kansas_city")
        self.assertEqual(GAPS["college"]["status"], "not_configured")
        self.assertIn("streaming entitlement", RIGHTS_NOTE.lower())

    def test_ops_dashboard_includes_feeds(self):
        cfg = Config(env="demo", allowed_origins=["http://127.0.0.1"])
        db = Database(":memory:")
        seed_if_empty(db)
        cp = ControlPlane(db, cfg)
        payload = cp.ops_dashboard(cp.get_user("demo-worker"))
        self.assertIn("sports_feeds", payload)
        blob = json.dumps(payload).lower()
        self.assertNotIn("api_token", blob)
        self.assertNotIn("signing_secret", blob)


if __name__ == "__main__":
    unittest.main()
