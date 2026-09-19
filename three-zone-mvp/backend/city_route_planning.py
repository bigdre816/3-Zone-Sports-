"""THREEZONE City: canonical places + Getting There route planning.

Milestone A only. This module deliberately stops before embedded native guidance.
It owns canonical destination identity and server-side route estimates; native
Navigation SDK lifecycle/telemetry belongs to the next gated milestone.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

GOOGLE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
DEFAULT_EARLY_ARRIVAL_MINUTES = 10
DEFAULT_PARKING_WALKING_MINUTES = 10
MAX_ALLOWANCE_MINUTES = 120
MAX_ROUTE_REQUESTS = 2


class RoutePlanningError(Exception):
    """Safe product error for a City route-planning request."""

    def __init__(self, message: str, code: str = "route_planning_error", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _epoch(value: datetime) -> float:
    return value.astimezone(timezone.utc).timestamp()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any, *, default_timezone: str | None = None) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise RoutePlanningError("time is required", "time_required")
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RoutePlanningError("invalid time", "invalid_time") from exc
    if parsed.tzinfo is None:
        if not default_timezone:
            raise RoutePlanningError("timezone is required for local time", "timezone_required")
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
        except ZoneInfoNotFoundError as exc:
            raise RoutePlanningError("invalid timezone", "invalid_timezone") from exc
    return parsed.astimezone(timezone.utc)


def _coerce_allowance(value: Any, default: int, name: str) -> int:
    if value in (None, ""):
        return default
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise RoutePlanningError(f"{name} must be whole minutes", "invalid_allowance") from exc
    if minutes < 0 or minutes > MAX_ALLOWANCE_MINUTES:
        raise RoutePlanningError(
            f"{name} must be between 0 and {MAX_ALLOWANCE_MINUTES} minutes",
            "invalid_allowance",
        )
    return minutes


def _duration_seconds(raw: Any) -> int:
    text = str(raw or "").strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", text)
    if not match:
        raise RoutePlanningError("route provider returned an invalid duration", "provider_bad_response", 502)
    return max(0, int(round(float(match.group(1)))))


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _normalized_name(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(value or "").lower()).split())


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _valid_coordinate(latitude: Any, longitude: Any) -> tuple[float, float]:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise RoutePlanningError("valid destination coordinates are required", "missing_destination_coordinates") from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise RoutePlanningError("valid destination coordinates are required", "missing_destination_coordinates")
    return lat, lon


CITY_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS city_places (
        city_place_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        latitude DOUBLE PRECISION NOT NULL,
        longitude DOUBLE PRECISION NOT NULL,
        address TEXT NOT NULL,
        neighborhood TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL,
        source_ids TEXT NOT NULL DEFAULT '{}',
        provenance TEXT NOT NULL DEFAULT '{}',
        last_verified_at DOUBLE PRECISION NOT NULL,
        rights_use_class TEXT NOT NULL DEFAULT 'unknown',
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS city_events (
        city_event_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        city_place_id TEXT NOT NULL,
        starts_at DOUBLE PRECISION,
        timezone TEXT NOT NULL DEFAULT 'America/Chicago',
        status TEXT NOT NULL DEFAULT 'scheduled',
        source TEXT NOT NULL,
        source_event_id TEXT,
        last_verified_at DOUBLE PRECISION NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_city_events_place_start ON city_events(city_place_id, starts_at)",
)


class CityRepository:
    """Canonical place/event storage. No provider secret or raw route history is stored."""

    def __init__(self, db):
        self.db = db
        self.ensure_schema()

    def ensure_schema(self) -> None:
        for statement in CITY_SCHEMA:
            self.db.execute(statement)

    def get_place(self, city_place_id: str) -> dict[str, Any]:
        row = _row_dict(self.db.query_one("SELECT * FROM city_places WHERE city_place_id=?", (city_place_id,)))
        if not row:
            raise RoutePlanningError("city place not found", "city_place_not_found", 404)
        row["source_ids"] = _json_object(row.get("source_ids"))
        row["provenance"] = _json_object(row.get("provenance"))
        return row

    def get_event(self, city_event_id: str) -> dict[str, Any]:
        row = _row_dict(self.db.query_one("SELECT * FROM city_events WHERE city_event_id=?", (city_event_id,)))
        if not row:
            raise RoutePlanningError("city event not found", "city_event_not_found", 404)
        return row

    def event_detail(self, city_event_id: str) -> dict[str, Any]:
        event = self.get_event(city_event_id)
        place = self.get_place(event["city_place_id"])
        return {"event": event, "place": place}

    def match_or_create_place(
        self,
        *,
        city_place_id: str,
        name: str,
        place_type: str,
        latitude: float,
        longitude: float,
        address: str,
        source: str,
        source_id: str | None = None,
        neighborhood: str = "",
        provenance: dict[str, Any] | None = None,
        rights_use_class: str = "unknown",
        verified_at: float | None = None,
    ) -> dict[str, Any]:
        """Resolve provider ID first, then coordinate + name evidence.

        Similar names alone never merge. A proximity/name match requires <=150 m and
        a normalized-name similarity >=0.72. Provider IDs are remembered after a
        match so later resolution is deterministic.
        """
        lat, lon = _valid_coordinate(latitude, longitude)
        name = str(name or "").strip()
        address = str(address or "").strip()
        source = str(source or "").strip()
        if not city_place_id or not name or not address or not source:
            raise RoutePlanningError("place id, name, address, and source are required", "invalid_city_place")

        rows = [_row_dict(r) or {} for r in self.db.query("SELECT * FROM city_places")]
        selected: dict[str, Any] | None = None
        if source_id:
            for candidate in rows:
                ids = _json_object(candidate.get("source_ids"))
                if str(ids.get(source) or "") == str(source_id):
                    selected = candidate
                    break

        if selected is None:
            needle = _normalized_name(name)
            matches: list[tuple[float, float, dict[str, Any]]] = []
            for candidate in rows:
                try:
                    distance = _haversine_meters(lat, lon, float(candidate["latitude"]), float(candidate["longitude"]))
                except (TypeError, ValueError, KeyError):
                    continue
                similarity = SequenceMatcher(None, needle, _normalized_name(candidate.get("name") or "")).ratio()
                if distance <= 150.0 and similarity >= 0.72:
                    matches.append((distance, -similarity, candidate))
            if matches:
                matches.sort(key=lambda item: (item[0], item[1]))
                selected = matches[0][2]

        now = float(verified_at if verified_at is not None else time.time())
        ids = _json_object((selected or {}).get("source_ids"))
        if source_id:
            ids[source] = str(source_id)
        prov = _json_object((selected or {}).get("provenance"))
        if provenance:
            prov[source] = dict(provenance)

        if selected is not None:
            place_id = selected["city_place_id"]
            self.db.execute(
                "UPDATE city_places SET name=?, type=?, latitude=?, longitude=?, address=?, neighborhood=?, "
                "source=?, source_ids=?, provenance=?, last_verified_at=?, rights_use_class=?, updated_at=? "
                "WHERE city_place_id=?",
                (
                    name, place_type, lat, lon, address, neighborhood, source,
                    json.dumps(ids, sort_keys=True), json.dumps(prov, sort_keys=True),
                    now, rights_use_class, now, place_id,
                ),
            )
            return self.get_place(place_id)

        self.db.execute(
            "INSERT INTO city_places(city_place_id,name,type,latitude,longitude,address,neighborhood,source,source_ids,"
            "provenance,last_verified_at,rights_use_class,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                city_place_id, name, place_type, lat, lon, address, neighborhood, source,
                json.dumps(ids, sort_keys=True), json.dumps(prov, sort_keys=True), now,
                rights_use_class, now, now,
            ),
        )
        return self.get_place(city_place_id)

    def upsert_event(
        self,
        *,
        city_event_id: str,
        title: str,
        city_place_id: str,
        starts_at: float | datetime | None,
        timezone_name: str,
        source: str,
        source_event_id: str | None = None,
        status: str = "scheduled",
        verified_at: float | None = None,
    ) -> dict[str, Any]:
        self.get_place(city_place_id)
        now = float(verified_at if verified_at is not None else time.time())
        if isinstance(starts_at, datetime):
            start_epoch = _epoch(starts_at)
        elif starts_at is None:
            start_epoch = None
        else:
            start_epoch = float(starts_at)
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise RoutePlanningError("invalid event timezone", "invalid_timezone") from exc
        existing = self.db.query_one("SELECT city_event_id FROM city_events WHERE city_event_id=?", (city_event_id,))
        if existing:
            self.db.execute(
                "UPDATE city_events SET title=?,city_place_id=?,starts_at=?,timezone=?,status=?,source=?,source_event_id=?,"
                "last_verified_at=?,updated_at=? WHERE city_event_id=?",
                (title, city_place_id, start_epoch, timezone_name, status, source, source_event_id, now, now, city_event_id),
            )
        else:
            self.db.execute(
                "INSERT INTO city_events(city_event_id,title,city_place_id,starts_at,timezone,status,source,source_event_id,"
                "last_verified_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (city_event_id, title, city_place_id, start_epoch, timezone_name, status, source, source_event_id, now, now, now),
            )
        return self.get_event(city_event_id)


@dataclass(frozen=True)
class RouteEstimate:
    duration_seconds: int
    distance_meters: int
    estimated_at: datetime
    departure_time: datetime
    provider: str = "google_routes"


class GoogleRoutesClient:
    """Minimal server-side adapter for Routes API v2 ComputeRoutes."""

    def __init__(self, api_key: str | None = None, *, timeout_seconds: float = 8.0):
        self.api_key = (api_key if api_key is not None else os.environ.get("TZ_GOOGLE_ROUTES_API_KEY", "")).strip()
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _waypoint(value: dict[str, Any]) -> dict[str, Any]:
        if value.get("address"):
            return {"address": str(value["address"]).strip()}
        if value.get("place_id"):
            return {"placeId": str(value["place_id"]).strip()}
        lat = value.get("latitude")
        lon = value.get("longitude")
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError) as exc:
            raise RoutePlanningError("origin must include an address or coordinates", "origin_required") from exc
        if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
            raise RoutePlanningError("origin coordinates are invalid", "invalid_origin")
        return {"location": {"latLng": {"latitude": lat_f, "longitude": lon_f}}}

    def estimate(self, *, origin: dict[str, Any], destination: dict[str, Any], departure_time: datetime) -> RouteEstimate:
        if not self.configured:
            raise RoutePlanningError("Google Routes is not configured", "route_provider_not_configured", 503)
        departure_time = departure_time.astimezone(timezone.utc)
        if departure_time < _utc_now() - timedelta(seconds=30):
            departure_time = _utc_now()
        payload = {
            "origin": self._waypoint(origin),
            "destination": self._waypoint(destination),
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
            "trafficModel": "BEST_GUESS",
            "departureTime": _iso(departure_time),
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "regionCode": "us",
            "units": "IMPERIAL",
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            GOOGLE_ROUTES_URL,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.staticDuration",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = "route_provider_rejected"
            if exc.code in (401, 403):
                code = "route_provider_auth"
            elif exc.code == 429:
                code = "route_provider_rate_limited"
            raise RoutePlanningError("route estimate unavailable right now", code, 503) from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RoutePlanningError("route estimate unavailable right now", "route_provider_unavailable", 503) from exc
        routes = data.get("routes") if isinstance(data, dict) else None
        if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
            raise RoutePlanningError("no drivable route was returned", "route_unavailable", 422)
        route = routes[0]
        try:
            distance = int(route.get("distanceMeters") or 0)
        except (TypeError, ValueError):
            distance = 0
        return RouteEstimate(
            duration_seconds=_duration_seconds(route.get("duration")),
            distance_meters=max(0, distance),
            estimated_at=_utc_now(),
            departure_time=departure_time,
        )


class RoutePlanningService:
    """Provider-neutral planning interface used by Getting There."""

    def __init__(
        self,
        db,
        *,
        routes_client: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.repo = CityRepository(db)
        self.routes = routes_client if routes_client is not None else GoogleRoutesClient()
        self.clock = clock or _utc_now

    def _origin(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise RoutePlanningError("choose Use my location or enter a starting address", "origin_required")
        address = str(raw.get("address") or "").strip()
        if address:
            return {"address": address, "kind": "manual_address"}
        if raw.get("latitude") is not None and raw.get("longitude") is not None:
            lat, lon = _valid_coordinate(raw.get("latitude"), raw.get("longitude"))
            return {"latitude": lat, "longitude": lon, "kind": "precise_location"}
        raise RoutePlanningError("choose Use my location or enter a starting address", "origin_required")

    @staticmethod
    def _destination(place: dict[str, Any]) -> dict[str, Any]:
        lat, lon = _valid_coordinate(place.get("latitude"), place.get("longitude"))
        return {"latitude": lat, "longitude": lon}

    @staticmethod
    def _directions_url(place: dict[str, Any]) -> str:
        destination = place.get("address") or f"{place['latitude']},{place['longitude']}"
        return "https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote(str(destination))

    def estimate_getting_there(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise RoutePlanningError("JSON object required", "bad_request")
        city_event_id = str(body.get("city_event_id") or "").strip()
        city_place_id = str(body.get("city_place_id") or "").strip()
        event: dict[str, Any] | None = None
        if city_event_id:
            event = self.repo.get_event(city_event_id)
            city_place_id = event["city_place_id"]
        if not city_place_id:
            raise RoutePlanningError("city_event_id or city_place_id is required", "destination_required")
        place = self.repo.get_place(city_place_id)
        destination = self._destination(place)
        origin = self._origin(body.get("origin"))

        if event and str(event.get("status") or "").lower() in {"cancelled", "canceled", "postponed"}:
            raise RoutePlanningError("this event is not currently plannable", "event_not_plannable", 422)

        early_minutes = _coerce_allowance(
            body.get("early_arrival_minutes"),
            DEFAULT_EARLY_ARRIVAL_MINUTES if event and event.get("starts_at") is not None else 0,
            "early_arrival_minutes",
        )
        parking_minutes = _coerce_allowance(
            body.get("parking_walking_minutes"),
            DEFAULT_PARKING_WALKING_MINUTES,
            "parking_walking_minutes",
        )

        event_start: datetime | None = None
        if event and event.get("starts_at") is not None:
            event_start = datetime.fromtimestamp(float(event["starts_at"]), tz=timezone.utc)
            desired_arrival = event_start - timedelta(minutes=early_minutes)
        elif body.get("desired_arrival_at"):
            desired_arrival = _parse_datetime(
                body.get("desired_arrival_at"),
                default_timezone=(event or {}).get("timezone") or body.get("timezone"),
            )
        else:
            raise RoutePlanningError(
                "this event has no exact start; choose an arrival time",
                "arrival_time_required",
                422,
            )

        now = self.clock().astimezone(timezone.utc)
        request_count = 0
        first = self.routes.estimate(origin=origin, destination=destination, departure_time=now)
        request_count += 1
        candidate = desired_arrival - timedelta(minutes=parking_minutes, seconds=first.duration_seconds)
        selected = first

        # One bounded future recheck. Driving ComputeRoutes accepts departureTime;
        # arrivalTime is a transit-only input, so we work backward from the target.
        if candidate > now + timedelta(seconds=60) and request_count < MAX_ROUTE_REQUESTS:
            future = self.routes.estimate(origin=origin, destination=destination, departure_time=candidate)
            request_count += 1
            selected = future
            candidate = desired_arrival - timedelta(minutes=parking_minutes, seconds=future.duration_seconds)

        leave_now = candidate <= now
        recommended_departure = now if leave_now else candidate
        estimated_arrival = recommended_departure + timedelta(seconds=selected.duration_seconds, minutes=parking_minutes)
        seconds_late = max(0, int((estimated_arrival - desired_arrival).total_seconds())) if leave_now else 0

        timezone_name = (event or {}).get("timezone") or "America/Chicago"
        try:
            local_zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            local_zone = timezone.utc
        explanation_parts = []
        if event_start is not None:
            explanation_parts.append(
                f"Event starts {event_start.astimezone(local_zone).strftime('%-I:%M %p')} {timezone_name}."
            )
            explanation_parts.append(f"Arrival allowance: {early_minutes} minutes before start.")
        else:
            explanation_parts.append("Arrival target was selected by the member.")
        explanation_parts.append(f"Parking/walking allowance: {parking_minutes} minutes.")
        explanation_parts.append(f"Traffic-aware drive estimate: {round(selected.duration_seconds / 60)} minutes.")
        if leave_now:
            if seconds_late > 0:
                explanation_parts.append(
                    f"The preferred departure has passed; leaving now is estimated to reach the arrival target about {math.ceil(seconds_late / 60)} minutes late."
                )
            else:
                explanation_parts.append("The preferred departure has passed; leave now for the best current estimate.")
        elif request_count == 2:
            explanation_parts.append("Drive time was rechecked for the proposed future departure.")

        return {
            "state": "route_ready",
            "city_event_id": city_event_id or None,
            "city_place_id": city_place_id,
            "destination": {
                "name": place["name"],
                "address": place["address"],
                "neighborhood": place.get("neighborhood") or "",
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "last_verified_at": place["last_verified_at"],
                "rights_use_class": place.get("rights_use_class") or "unknown",
            },
            "event": None if event is None else {
                "title": event["title"],
                "status": event["status"],
                "starts_at": _iso(event_start),
                "timezone": timezone_name,
                "source": event["source"],
                "last_verified_at": event["last_verified_at"],
            },
            "origin_kind": origin["kind"],
            "travel_mode": "DRIVE",
            "route": {
                "provider": selected.provider,
                "duration_seconds": selected.duration_seconds,
                "duration_minutes": round(selected.duration_seconds / 60),
                "distance_meters": selected.distance_meters,
                "estimated_for_departure_at": _iso(selected.departure_time),
                "last_successful_estimate_at": _iso(selected.estimated_at),
                "request_count": request_count,
                "traffic_aware": True,
            },
            "planning_allowances": {
                "early_arrival_minutes": early_minutes,
                "parking_walking_minutes": parking_minutes,
                "editable": True,
                "kind": "planning_allowance",
            },
            "desired_arrival_at": _iso(desired_arrival),
            "suggested_departure_at": _iso(recommended_departure),
            "estimated_arrival_at": _iso(estimated_arrival),
            "leave_now": leave_now,
            "estimated_late_seconds": seconds_late,
            "explanation": " ".join(explanation_parts),
            "directions_fallback_url": self._directions_url(place),
            "start_navigation_available": False,
            "navigation_gate": "native_navigation_not_integrated",
        }
