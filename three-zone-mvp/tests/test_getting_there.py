"""Milestone A Getting There — departure math, fail-closed planning, city places."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.city.departure import desired_arrival, suggested_departure
from backend.city.directions import external_directions_url
from backend.city.navigation import NavigationService
from backend.city.places import CityPlaceService, KC_SPORTS_ANCHORS
from backend.city.route_planning import RoutePlanningService
from backend.city.routes_provider import DriveEstimate, RoutesProviderError
from backend.city.signals import (
    DIRECTIONS_REQUESTED,
    NAVIGATION_ARRIVED,
    NAVIGATION_ROUTE_READY,
    NAVIGATION_STARTED,
    CitySignalService,
    SignalError,
)
from backend.config import Config
from backend.control_plane import ControlPlane, SITE_ROUTES, ValidationError
from backend.db import Database, loads
from backend.http_server import make_http_server
from backend.seed import seed_if_empty
from backend.sports_feeds.normalize import normalize_game

MVP = Path(__file__).resolve().parents[1]
CHICAGO = ZoneInfo("America/Chicago")
ORIGIN_OP = {"lat": 38.9822, "lng": -94.6708, "label": "Overland Park"}


class FakeRoutesProvider:
    def __init__(self, duration_seconds=1500, distance_meters=20000, fail=None, sequence=None):
        self.configured = True
        self.calls = []
        self.fail = fail
        self.sequence = list(sequence or [])
        self.duration_seconds = duration_seconds
        self.distance_meters = distance_meters

    def compute_drive(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail
        if self.sequence:
            duration = self.sequence.pop(0)
        else:
            duration = self.duration_seconds
        return DriveEstimate(
            duration_seconds=duration,
            distance_meters=self.distance_meters,
            departure_time=kwargs["departure_time"],
            routing_preference="TRAFFIC_AWARE",
        )


def _stack(key="", provider=None, clock=None):
    cfg = Config(
        env="demo",
        allowed_origins=["http://127.0.0.1"],
        google_maps_api_key=key,
    )
    db = Database(":memory:")
    seed_if_empty(db)
    places = CityPlaceService(db)
    places.ensure_seeded()
    signals = CitySignalService(db)
    nav = NavigationService()
    planner = RoutePlanningService(
        cfg, places, signals, provider=provider, navigation=nav, clock=clock,
    )
    return cfg, db, places, signals, planner


def _member():
    return {"user_id": "demo-viewer", "role": "viewer"}


class DepartureMathTests(unittest.TestCase):
    def test_fixture_400pm_minus_allowances_is_315pm(self):
        event = datetime(2026, 9, 20, 16, 0, tzinfo=CHICAGO)
        arrive = desired_arrival(event, 10)
        self.assertEqual(arrive, datetime(2026, 9, 20, 15, 50, tzinfo=CHICAGO))
        depart = suggested_departure(
            event,
            desired_arrival_offset_minutes=10,
            parking_or_walk_minutes=10,
            drive_duration_seconds=25 * 60,
        )
        self.assertEqual(depart, datetime(2026, 9, 20, 15, 15, tzinfo=CHICAGO))
        self.assertEqual(depart.hour, 15)
        self.assertEqual(depart.minute, 15)


class PlaceSeedTests(unittest.TestCase):
    def test_kc_anchors_seed_and_sports_resolve(self):
        _, db, places, _, _ = _stack()
        ids = {p["city_place_id"] for p in places.list_places(vertical="sports")}
        self.assertEqual(ids, {"plc_kc_arrowhead", "plc_kc_kauffman"})
        self.assertEqual(places.get("plc_kc_arrowhead")["name"], "GEHA Field at Arrowhead Stadium")
        chiefs_home = {
            "venue": "GEHA Field at Arrowhead Stadium",
            "home": {"team_id": "team_nfl_kc_chiefs"},
            "away": {"team_id": "team_nfl_bal_ravens"},
        }
        self.assertEqual(places.resolve_for_game(chiefs_home)["city_place_id"], "plc_kc_arrowhead")
        royals_home = {
            "venue": "Kauffman Stadium",
            "home": {"team_id": "team_mlb_kc_royals"},
            "away": {"team_id": "team_mlb_nyy"},
        }
        self.assertEqual(places.resolve_for_game(royals_home)["city_place_id"], "plc_kc_kauffman")
        away = {
            "venue": "M&T Bank Stadium",
            "home": {"team_id": "team_nfl_bal_ravens"},
            "away": {"team_id": "team_nfl_kc_chiefs"},
        }
        self.assertIsNone(places.resolve_for_game(away))
        game = normalize_game(
            "NFL",
            {
                "id": 7001,
                "home_team": {"id": 14, "full_name": "Kansas City Chiefs", "abbreviation": "KC"},
                "visitor_team": {"id": 6, "full_name": "Baltimore Ravens", "abbreviation": "BAL"},
                "venue": "GEHA Field at Arrowhead Stadium",
                "datetime": "2024-09-06T00:20:00.000Z",
                "status": "scheduled",
            },
            retrieved_at=datetime(2026, 9, 19, tzinfo=CHICAGO),
        )
        annotated = places.annotate_game(game)
        self.assertEqual(annotated["city_place_id"], "plc_kc_arrowhead")
        self.assertEqual(len(KC_SPORTS_ANCHORS), 2)


class SignalTests(unittest.TestCase):
    def test_forbidden_native_signals_and_no_coords(self):
        _, db, _, signals, _ = _stack()
        with self.assertRaises(SignalError):
            signals.emit(NAVIGATION_STARTED, member_id="demo-viewer", city_place_id="plc_kc_arrowhead")
        with self.assertRaises(SignalError):
            signals.emit(NAVIGATION_ARRIVED, member_id="demo-viewer", city_place_id="plc_kc_arrowhead")
        first = signals.emit(
            DIRECTIONS_REQUESTED,
            member_id="demo-viewer",
            city_place_id="plc_kc_arrowhead",
            request_id="req-1",
            payload={"lat": 39.0, "lng": -94.4, "city_place_id": "plc_kc_arrowhead"},
        )
        self.assertFalse(first["deduped"])
        again = signals.emit(
            DIRECTIONS_REQUESTED,
            member_id="demo-viewer",
            city_place_id="plc_kc_arrowhead",
            request_id="req-1",
        )
        self.assertTrue(again["deduped"])
        row = db.query_one("SELECT payload FROM city_signals WHERE signal_id=?", (first["signal_id"],))
        payload = loads(row["payload"])
        self.assertNotIn("lat", payload)
        self.assertNotIn("lng", payload)
        self.assertEqual(payload["city_place_id"], "plc_kc_arrowhead")


class PlanningServiceTests(unittest.TestCase):
    def test_missing_coords_fail_closed(self):
        _, _, _, _, planner = _stack(provider=FakeRoutesProvider())
        with self.assertRaises(ValidationError) as raised:
            planner.plan(_member(), {"city_place_id": "plc_kc_arrowhead"})
        self.assertEqual(raised.exception.code, "origin_coordinates_required")
        with self.assertRaises(ValidationError) as raised:
            planner.plan(_member(), {
                "city_place_id": "plc_kc_arrowhead",
                "origin": {"address": "123 Main St, Kansas City, MO"},
            })
        self.assertEqual(raised.exception.code, "origin_coordinates_required")

    def test_missing_place_required(self):
        _, _, _, _, planner = _stack(provider=FakeRoutesProvider())
        with self.assertRaises(ValidationError) as raised:
            planner.plan(_member(), {"origin": ORIGIN_OP})
        self.assertEqual(raised.exception.code, "city_place_required")

    def test_missing_key_hold_does_not_invent_times(self):
        fake = FakeRoutesProvider()
        fake.configured = False
        _, db, _, _, planner = _stack(key="", provider=fake)
        result = planner.plan(_member(), {
            "city_place_id": "plc_kc_arrowhead",
            "origin": ORIGIN_OP,
            "event_starts_at": "2026-09-20T21:00:00Z",
            "request_id": "hold-key",
        })
        self.assertEqual(result["status"], "hold")
        self.assertEqual(result["code"], "routes_not_configured")
        self.assertIsNone(result["suggested_departure"])
        self.assertIsNone(result["drive"])
        self.assertEqual(fake.calls, [])
        types = [r["event_type"] for r in db.query("SELECT event_type FROM city_signals")]
        self.assertIn(DIRECTIONS_REQUESTED, types)
        self.assertNotIn(NAVIGATION_ROUTE_READY, types)
        self.assertNotIn(NAVIGATION_STARTED, types)

    def test_provider_failure_hold(self):
        fake = FakeRoutesProvider(fail=RoutesProviderError("provider_error", "boom"))
        clock = lambda: datetime(2026, 9, 20, 12, 0, tzinfo=CHICAGO)
        _, db, _, _, planner = _stack(key="test-key", provider=fake, clock=clock)
        result = planner.plan(_member(), {
            "city_place_id": "plc_kc_arrowhead",
            "origin": ORIGIN_OP,
            "event_starts_at": "2026-09-20T21:00:00Z",
            "request_id": "hold-provider",
        })
        self.assertEqual(result["status"], "hold")
        self.assertEqual(result["code"], "provider_error")
        self.assertIsNone(result["suggested_departure"])
        self.assertIsNone(result["drive"])
        types = [r["event_type"] for r in db.query("SELECT event_type FROM city_signals")]
        self.assertNotIn(NAVIGATION_ROUTE_READY, types)

    def test_successful_plan_fixture_and_signals(self):
        event = datetime(2026, 9, 20, 16, 0, tzinfo=CHICAGO)
        clock = lambda: datetime(2026, 9, 20, 12, 0, tzinfo=CHICAGO)
        fake = FakeRoutesProvider(duration_seconds=25 * 60)
        _, db, _, _, planner = _stack(key="test-key", provider=fake, clock=clock)
        result = planner.plan(_member(), {
            "city_place_id": "plc_kc_arrowhead",
            "origin": ORIGIN_OP,
            "event_starts_at": event.isoformat(),
            "desired_arrival_offset_minutes": 10,
            "parking_or_walk_minutes": 10,
            "request_id": "ok-1",
        })
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["drive"]["duration_seconds"], 1500)
        self.assertEqual(result["allowances"]["label"], "planning allowances")
        local = datetime.fromisoformat(result["suggested_departure_local"])
        self.assertEqual(local.hour, 15)
        self.assertEqual(local.minute, 15)
        self.assertIsNotNone(result["last_successful_estimate_at"])
        self.assertFalse(result["navigation"]["native"])
        self.assertTrue(fake.calls)
        self.assertIn("departure_time", fake.calls[0])
        blob = json.dumps(result)
        self.assertNotIn("test-key", blob)
        types = {r["event_type"] for r in db.query("SELECT event_type FROM city_signals")}
        self.assertEqual(types, {DIRECTIONS_REQUESTED, NAVIGATION_ROUTE_READY})
        for row in db.query("SELECT payload FROM city_signals"):
            payload = loads(row["payload"])
            self.assertNotIn("lat", json.dumps(payload))
            self.assertNotIn("38.9822", json.dumps(payload))

    def test_past_deadline_leave_now(self):
        event = datetime(2026, 9, 20, 16, 0, tzinfo=CHICAGO)
        clock = lambda: datetime(2026, 9, 20, 15, 40, tzinfo=CHICAGO)
        fake = FakeRoutesProvider(duration_seconds=25 * 60)
        _, _, _, _, planner = _stack(key="k", provider=fake, clock=clock)
        result = planner.plan(_member(), {
            "city_place_id": "plc_kc_kauffman",
            "origin": ORIGIN_OP,
            "event_starts_at": event.isoformat(),
            "request_id": "late-1",
        })
        self.assertEqual(result["status"], "leave_now")
        self.assertEqual(result["code"], "departure_passed")
        self.assertIn("already passed", result["explanation"])
        self.assertIsNotNone(result["likely_arrival"])
        self.assertGreater(result["late_by_seconds"], 0)
        self.assertEqual(result["drive"]["duration_seconds"], 1500)

    def test_bounded_iteration_converges(self):
        event = datetime(2026, 9, 20, 16, 0, tzinfo=CHICAGO)
        clock = lambda: datetime(2026, 9, 20, 10, 0, tzinfo=CHICAGO)
        fake = FakeRoutesProvider(sequence=[30 * 60, 25 * 60, 25 * 60])
        _, _, _, _, planner = _stack(key="k", provider=fake, clock=clock)
        result = planner.plan(_member(), {
            "city_place_id": "plc_kc_arrowhead",
            "origin": ORIGIN_OP,
            "event_starts_at": event.isoformat(),
            "request_id": "iter-1",
        })
        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(result["iteration"]["count"], 3)
        self.assertTrue(result["iteration"]["bounded"])
        self.assertLessEqual(len(fake.calls), 3)

    def test_directions_url_does_not_emit_started_or_ready(self):
        _, db, _, _, planner = _stack(provider=FakeRoutesProvider())
        result = planner.directions_url(_member(), {
            "city_place_id": "plc_kc_arrowhead",
            "origin": ORIGIN_OP,
            "request_id": "url-1",
        })
        self.assertTrue(result["directions_url"].startswith("https://www.google.com/maps/dir/?"))
        self.assertFalse(result["emits_navigation_started"])
        self.assertFalse(result["navigation"]["native"])
        types = [r["event_type"] for r in db.query("SELECT event_type FROM city_signals")]
        self.assertEqual(types, [DIRECTIONS_REQUESTED])
        self.assertNotIn(NAVIGATION_STARTED, types)
        self.assertNotIn(NAVIGATION_ROUTE_READY, types)
        url = external_directions_url(dest_lat=39.0489, dest_lng=-94.4839)
        self.assertIn("destination=", url)

    def test_navigation_stub_is_not_native(self):
        cap = NavigationService().capability()
        self.assertFalse(cap["native"])
        self.assertFalse(cap["turn_by_turn"])
        self.assertEqual(cap["milestone"], "B")
        self.assertFalse(cap["emits_navigation_started"])


class GettingThereHttpTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                          allowed_origins=["http://127.0.0.1"])
        self.db = Database(":memory:")
        seed_if_empty(self.db)
        self.cp = ControlPlane(self.db, self.cfg)
        self.httpd = make_http_server(
            self.cfg, self.cp, "/tmp", start_feed_poller=False,
        )
        fake = FakeRoutesProvider(duration_seconds=25 * 60)
        clock = lambda: datetime(2026, 9, 20, 12, 0, tzinfo=CHICAGO)
        self.httpd.RequestHandlerClass.route_planning.provider = fake
        self.httpd.RequestHandlerClass.route_planning._clock = clock
        self.fake = fake
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _login(self):
        req = urllib.request.Request(
            self.base + "/api/auth/login",
            data=json.dumps({"username": "demo-viewer", "password": "change-me-viewer-local"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())["session_token"]

    def _post(self, path, token, body, expect=200):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode() or "{}")
            if expect and exc.code != expect:
                raise AssertionError(f"{path} -> {exc.code} {payload}")
            return exc.code, payload

    def _get(self, path, token=None):
        req = urllib.request.Request(self.base + path)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def test_unauthenticated_city_routes(self):
        status, payload = self._get("/api/member/city/places")
        self.assertEqual(status, 401)
        self.assertEqual(payload.get("code"), "missing_session")
        status, payload = self._post("/api/member/city/routes/plan", "", {
            "city_place_id": "plc_kc_arrowhead", "origin": ORIGIN_OP,
        }, expect=401)
        self.assertEqual(status, 401)

    def test_member_places_and_plan(self):
        token = self._login()
        status, payload = self._get("/api/member/city/places", token)
        self.assertEqual(status, 200)
        ids = {p["city_place_id"] for p in payload["places"]}
        self.assertIn("plc_kc_arrowhead", ids)
        self.assertIn("plc_kc_kauffman", ids)
        status, plan = self._post("/api/member/city/routes/plan", token, {
            "city_place_id": "plc_kc_arrowhead",
            "origin": ORIGIN_OP,
            "event_starts_at": "2026-09-20T21:00:00Z",
            "request_id": "http-ok",
        })
        self.assertEqual(status, 200)
        self.assertEqual(plan["status"], "ok")
        self.assertEqual(plan["destination"]["name"], "GEHA Field at Arrowhead Stadium")
        self.assertIsNotNone(plan["last_successful_estimate_at"])
        self.assertFalse(plan["navigation"]["native"])
        status, cap = self._get("/api/member/city/navigation/capability", token)
        self.assertEqual(status, 200)
        self.assertFalse(cap["native"])
        health = json.loads(urllib.request.urlopen(self.base + "/api/health", timeout=5).read())
        self.assertIn("getting_there", health)
        self.assertNotIn("GOOGLE_MAPS", json.dumps(health))
        cfg = json.loads(urllib.request.urlopen(self.base + "/api/config", timeout=5).read())
        self.assertFalse(cfg["getting_there"]["native_navigation"])
        self.assertTrue(cfg["getting_there"]["city_place_required"])
        self.assertNotIn("api_key", json.dumps(cfg).lower())

    def test_http_missing_coords(self):
        token = self._login()
        status, payload = self._post("/api/member/city/routes/plan", token, {
            "city_place_id": "plc_kc_arrowhead",
        }, expect=400)
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "origin_coordinates_required")


class ContractTests(unittest.TestCase):
    def test_routes_and_env_names(self):
        paths = {r["path"] for r in SITE_ROUTES}
        self.assertIn("/api/member/city/routes/plan", paths)
        self.assertIn("/api/member/city/directions-url", paths)
        env = (MVP / "config.example.env").read_text(encoding="utf-8")
        self.assertIn("GOOGLE_MAPS_API_KEY=", env)
        self.assertIn("GOOGLE_ROUTES_API_KEY=", env)
        self.assertNotRegex(env, r"GOOGLE_MAPS_API_KEY=.+")
        portal = (MVP / "backend" / "static" / "portal.js").read_text(encoding="utf-8")
        self.assertNotIn("/api/member/city/routes/plan", portal)


if __name__ == "__main__":
    unittest.main()
