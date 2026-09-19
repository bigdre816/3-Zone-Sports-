from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.city_route_planning import CityRepository, RouteEstimate, RoutePlanningError, RoutePlanningService
from backend.db import Database

CHICAGO = ZoneInfo("America/Chicago")


class FakeRoutes:
    def __init__(self, durations=(25 * 60,), *, estimated_at=None, fail=None):
        self.durations = list(durations)
        self.calls = []
        self.estimated_at = estimated_at
        self.fail = fail

    def estimate(self, *, origin, destination, departure_time):
        self.calls.append({"origin": dict(origin), "destination": dict(destination), "departure_time": departure_time})
        if self.fail:
            raise self.fail
        index = min(len(self.calls) - 1, len(self.durations) - 1)
        return RouteEstimate(
            duration_seconds=self.durations[index],
            distance_meters=16093,
            estimated_at=self.estimated_at or departure_time,
            departure_time=departure_time,
        )


def fixed_clock(local_iso: str):
    value = datetime.fromisoformat(local_iso).replace(tzinfo=CHICAGO).astimezone(timezone.utc)
    return lambda: value


def setup_city(start_local: str = "2026-09-19T16:00:00"):
    db = Database(":memory:")
    repo = CityRepository(db)
    place = repo.match_or_create_place(
        city_place_id="cp_kc_test_arena",
        name="Test Arena",
        place_type="sports_venue",
        latitude=39.0997,
        longitude=-94.5786,
        address="100 Test Way, Kansas City, MO 64106",
        neighborhood="Downtown",
        source="fixture",
        source_id="venue-100",
        provenance={"verified_by": "test"},
        rights_use_class="internal_test",
        verified_at=1_700_000_000,
    )
    start = datetime.fromisoformat(start_local).replace(tzinfo=CHICAGO)
    repo.upsert_event(
        city_event_id="ce_kc_test_game",
        title="Kansas City Test Game",
        city_place_id=place["city_place_id"],
        starts_at=start,
        timezone_name="America/Chicago",
        source="fixture",
        source_event_id="game-100",
        verified_at=1_700_000_100,
    )
    return db, repo, place


def test_city_places_schema_accepts_repository_insert_after_database_init():
    """db.py creates city_places first; CityRepository must still be able to write."""
    db, repo, place = setup_city()
    assert place["city_place_id"] == "cp_kc_test_arena"
    assert place["type"] == "sports_venue"
    stored = repo.get_place("cp_kc_test_arena")
    assert stored["source"] == "fixture"
    assert repo.get_event("ce_kc_test_game")["title"] == "Kansas City Test Game"
    cols = {row["name"] for row in db.query("PRAGMA table_info(city_places)")}
    assert {"type", "neighborhood", "source", "locality", "category"} <= cols


def test_city_repository_adds_missing_columns_on_preexisting_table():
    db = Database(":memory:")
    db.execute("DROP TABLE city_places")
    db.execute(
        "CREATE TABLE city_places ("
        "city_place_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL, "
        "locality TEXT NOT NULL, region TEXT NOT NULL, latitude REAL NOT NULL, "
        "longitude REAL NOT NULL, timezone TEXT NOT NULL DEFAULT 'America/Chicago', "
        "category TEXT NOT NULL, created_at REAL NOT NULL, recorded_at REAL NOT NULL)"
    )
    repo = CityRepository(db)
    place = repo.match_or_create_place(
        city_place_id="cp_legacy_arena",
        name="Legacy Arena",
        place_type="sports_venue",
        latitude=39.0997,
        longitude=-94.5786,
        address="100 Legacy Way",
        source="fixture",
    )
    assert place["type"] == "sports_venue"
    cols = {row["name"] for row in db.query("PRAGMA table_info(city_places)")}
    assert "type" in cols
    assert "source" in cols


def test_acceptance_fixture_departure_is_315_pm():
    db, _, _ = setup_city()
    fake = FakeRoutes((25 * 60, 25 * 60))
    svc = RoutePlanningService(db, routes_client=fake, clock=fixed_clock("2026-09-19T14:00:00"))
    result = svc.estimate_getting_there({
        "city_event_id": "ce_kc_test_game",
        "origin": {"address": "1 Main St, Kansas City, MO"},
        "early_arrival_minutes": 10,
        "parking_walking_minutes": 10,
    })
    departure = datetime.fromisoformat(result["suggested_departure_at"].replace("Z", "+00:00")).astimezone(CHICAGO)
    assert (departure.hour, departure.minute) == (15, 15)
    assert result["desired_arrival_at"] == "2026-09-19T20:50:00Z"
    assert result["route"]["duration_minutes"] == 25


def test_future_departure_is_rechecked_once_and_bounded():
    db, _, _ = setup_city()
    fake = FakeRoutes((20 * 60, 25 * 60, 99 * 60))
    svc = RoutePlanningService(db, routes_client=fake, clock=fixed_clock("2026-09-19T12:00:00"))
    result = svc.estimate_getting_there({"city_event_id": "ce_kc_test_game", "origin": {"latitude": 39.0, "longitude": -94.5}})
    assert len(fake.calls) == 2
    assert result["route"]["request_count"] == 2
    second_local = fake.calls[1]["departure_time"].astimezone(CHICAGO)
    assert (second_local.hour, second_local.minute) == (15, 20)
    final_local = datetime.fromisoformat(result["suggested_departure_at"].replace("Z", "+00:00")).astimezone(CHICAGO)
    assert (final_local.hour, final_local.minute) == (15, 15)


def test_past_preferred_departure_leaves_now_and_explains_lateness():
    db, _, _ = setup_city()
    fake = FakeRoutes((25 * 60,))
    svc = RoutePlanningService(db, routes_client=fake, clock=fixed_clock("2026-09-19T15:30:00"))
    result = svc.estimate_getting_there({"city_event_id": "ce_kc_test_game", "origin": {"address": "1 Main St"}})
    assert result["leave_now"] is True
    assert result["estimated_late_seconds"] == 15 * 60
    assert "preferred departure has passed" in result["explanation"].lower()
    assert len(fake.calls) == 1


def test_timezone_boundary_can_depart_previous_calendar_day():
    db, _, _ = setup_city("2026-09-20T00:05:00")
    svc = RoutePlanningService(db, routes_client=FakeRoutes((25 * 60, 25 * 60)), clock=fixed_clock("2026-09-19T21:00:00"))
    result = svc.estimate_getting_there({"city_event_id": "ce_kc_test_game", "origin": {"address": "1 Main St"}})
    departure = datetime.fromisoformat(result["suggested_departure_at"].replace("Z", "+00:00")).astimezone(CHICAGO)
    assert departure.date().isoformat() == "2026-09-19"
    assert (departure.hour, departure.minute) == (23, 20)


def test_manual_origin_is_forwarded():
    db, _, _ = setup_city()
    fake = FakeRoutes((25 * 60, 25 * 60))
    svc = RoutePlanningService(db, routes_client=fake, clock=fixed_clock("2026-09-19T14:00:00"))
    result = svc.estimate_getting_there({"city_event_id": "ce_kc_test_game", "origin": {"address": "Union Station, Kansas City, MO"}})
    assert fake.calls[0]["origin"]["address"] == "Union Station, Kansas City, MO"
    assert result["origin_kind"] == "manual_address"


def test_missing_origin_supports_denied_location_fallback_contract():
    db, _, _ = setup_city()
    svc = RoutePlanningService(db, routes_client=FakeRoutes(), clock=fixed_clock("2026-09-19T14:00:00"))
    with pytest.raises(RoutePlanningError) as caught:
        svc.estimate_getting_there({"city_event_id": "ce_kc_test_game"})
    assert caught.value.code == "origin_required"


def test_missing_destination_coordinates_are_rejected():
    db = Database(":memory:")
    repo = CityRepository(db)
    with pytest.raises(RoutePlanningError) as caught:
        repo.match_or_create_place(city_place_id="cp_bad", name="Bad Place", place_type="venue", latitude=None, longitude=None, address="100 Somewhere", source="fixture")
    assert caught.value.code == "missing_destination_coordinates"


def test_provider_failure_is_explicit():
    db, _, _ = setup_city()
    failure = RoutePlanningError("route estimate unavailable right now", "route_provider_unavailable", 503)
    svc = RoutePlanningService(db, routes_client=FakeRoutes(fail=failure), clock=fixed_clock("2026-09-19T14:00:00"))
    with pytest.raises(RoutePlanningError) as caught:
        svc.estimate_getting_there({"city_event_id": "ce_kc_test_game", "origin": {"address": "1 Main St"}})
    assert caught.value.code == "route_provider_unavailable"
    assert caught.value.status == 503


def test_last_successful_estimate_timestamp_is_not_render_time():
    db, _, _ = setup_city()
    estimated_at = datetime(2026, 9, 19, 19, 2, tzinfo=timezone.utc)
    svc = RoutePlanningService(db, routes_client=FakeRoutes((25 * 60, 25 * 60), estimated_at=estimated_at), clock=fixed_clock("2026-09-19T14:00:00"))
    result = svc.estimate_getting_there({"city_event_id": "ce_kc_test_game", "origin": {"address": "1 Main St"}})
    assert result["route"]["last_successful_estimate_at"] == "2026-09-19T19:02:00Z"


def test_cancelled_and_missing_exact_time_are_not_silently_planned():
    db, repo, place = setup_city()
    repo.upsert_event(city_event_id="ce_cancelled", title="Cancelled", city_place_id=place["city_place_id"], starts_at=datetime(2026, 9, 19, 16, 0, tzinfo=CHICAGO), timezone_name="America/Chicago", source="fixture", status="cancelled")
    repo.upsert_event(city_event_id="ce_no_time", title="Festival day", city_place_id=place["city_place_id"], starts_at=None, timezone_name="America/Chicago", source="fixture")
    svc = RoutePlanningService(db, routes_client=FakeRoutes(), clock=fixed_clock("2026-09-19T14:00:00"))
    with pytest.raises(RoutePlanningError) as cancelled:
        svc.estimate_getting_there({"city_event_id": "ce_cancelled", "origin": {"address": "1 Main St"}})
    assert cancelled.value.code == "event_not_plannable"
    with pytest.raises(RoutePlanningError) as no_time:
        svc.estimate_getting_there({"city_event_id": "ce_no_time", "origin": {"address": "1 Main St"}})
    assert no_time.value.code == "arrival_time_required"
