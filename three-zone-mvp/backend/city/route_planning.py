"""RoutePlanningService — Milestone A Getting There.

Traffic-aware drive via Google Routes computeRoutes (server-side).
Driving uses departureTime, not arrivalTime. Fail closed: missing key or
provider error never invents times.

Separate from NavigationService. Planning and the external directions URL
never emit navigation.started or navigation.arrived.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from ..control_plane import NotFoundError, ValidationError
from .departure import (
    DEFAULT_DESIRED_ARRIVAL_OFFSET_MINUTES,
    DEFAULT_PARKING_OR_WALK_MINUTES,
    clamp_allowance_minutes,
    desired_arrival,
    late_by_seconds,
    suggested_departure,
)
from .directions import external_directions_url
from .navigation import NavigationService
from .routes_provider import GoogleRoutesProvider, NotConfiguredError, RoutesProviderError
from .signals import DIRECTIONS_REQUESTED, NAVIGATION_ROUTE_READY

MAX_DEPARTURE_ITERS = 3
CONVERGE_SECONDS = 45


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_fields(dt: datetime | None, tz_name: str) -> dict:
    if dt is None:
        return {
            "utc": None,
            "local": None,
            "display_local": None,
            "timezone": tz_name,
            "date_kind": "event_local",
        }
    utc = _utc(dt)
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = ZoneInfo("America/Chicago")
        tz_name = "America/Chicago"
    local = utc.astimezone(zone)
    hour = local.strftime("%I").lstrip("0") or "12"
    return {
        "utc": iso_utc(utc),
        "local": local.isoformat(timespec="seconds"),
        "display_local": (
            f"{local.strftime('%a, %b')} {local.day} · {hour}:{local.strftime('%M %p')}"
        ),
        "timezone": tz_name,
        "date_kind": "event_local",
    }


def parse_event_time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _utc(dt)


def parse_origin(origin) -> tuple[float, float, str | None]:
    if not isinstance(origin, dict) or not origin:
        raise ValidationError(
            "origin lat/lng is required (one-time client coordinates or a labeled point). "
            "This host does not geocode a manual address.",
            "origin_coordinates_required",
        )
    lat = origin.get("lat", origin.get("latitude"))
    lng = origin.get("lng", origin.get("longitude"))
    if lat is None or lng is None:
        raise ValidationError(
            "origin lat/lng is required. Address-only origin is not geocoded on this host.",
            "origin_coordinates_required",
        )
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError) as exc:
        raise ValidationError("origin lat/lng must be numbers", "origin_coordinates_invalid") from exc
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0):
        raise ValidationError("origin lat/lng out of range", "origin_coordinates_invalid")
    label = str(origin.get("label") or "").strip() or None
    return lat_f, lng_f, label


class RoutePlanningService:
    """Member Getting There planner. Never invents drive times."""

    def __init__(
        self,
        config,
        places,
        signals,
        *,
        provider=None,
        navigation: NavigationService | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.config = config
        self.places = places
        self.signals = signals
        key = getattr(config, "routes_api_key", "") or ""
        self.provider = provider if provider is not None else GoogleRoutesProvider(key)
        self.navigation = navigation or NavigationService()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_successful_estimate_at: datetime | None = None

    @property
    def configured(self) -> bool:
        return bool(getattr(self.provider, "configured", False))

    @property
    def last_successful_estimate_at(self) -> datetime | None:
        return self._last_successful_estimate_at

    def health(self) -> dict:
        return {
            "routes_configured": self.configured,
            "native_navigation": False,
            "places": self.places.count() if self.places else 0,
            "last_successful_estimate_at": iso_utc(self._last_successful_estimate_at),
            "legal_effect": "provenance_only",
        }

    def plan(self, user: dict, body: dict | None, *, sports_feeds=None) -> dict:
        body = body or {}
        member_id = user["user_id"]
        request_id = str(body.get("request_id") or "").strip() or None
        origin_lat, origin_lng, origin_label = parse_origin(body.get("origin"))
        place, event_time, event_ref = self._resolve_destination(body, sports_feeds=sports_feeds)
        try:
            early = clamp_allowance_minutes(
                body.get("desired_arrival_offset_minutes"),
                DEFAULT_DESIRED_ARRIVAL_OFFSET_MINUTES,
            )
            parking = clamp_allowance_minutes(
                body.get("parking_or_walk_minutes"),
                DEFAULT_PARKING_OR_WALK_MINUTES,
            )
        except ValueError as exc:
            raise ValidationError(str(exc), "allowance_invalid") from exc

        self.signals.emit(
            DIRECTIONS_REQUESTED,
            member_id=member_id,
            city_place_id=place["city_place_id"],
            object_id=event_ref,
            request_id=request_id or f"plan_{place['city_place_id']}",
            payload={
                "surface": "routes.plan",
                "city_place_id": place["city_place_id"],
                "object_id": event_ref,
            },
        )

        tz_name = str(body.get("timezone") or place["timezone"] or "America/Chicago")
        now = self._clock()
        nav = self.navigation.capability()
        envelope = self._base(
            place, origin_label, early, parking, tz_name, event_time, event_ref, nav,
        )
        envelope["directions_url"] = external_directions_url(
            dest_lat=place["latitude"],
            dest_lng=place["longitude"],
            dest_name=place["name"],
            origin_lat=origin_lat,
            origin_lng=origin_lng,
        )

        if not self.configured:
            return self._hold(
                envelope,
                "routes_not_configured",
                "GOOGLE_MAPS_API_KEY / GOOGLE_ROUTES_API_KEY is not set. Drive times are not invented.",
            )

        try:
            estimate, iterations, used_departure, leave_now = self._estimate_drive(
                origin_lat, origin_lng, place, event_time, early, parking, now,
            )
        except NotConfiguredError:
            return self._hold(
                envelope,
                "routes_not_configured",
                "Routes provider is not configured. Drive times are not invented.",
            )
        except RoutesProviderError as exc:
            return self._hold(
                envelope,
                "provider_error",
                "Routes provider failed. Drive times are not invented.",
                provider_kind=exc.kind,
            )

        self._last_successful_estimate_at = now
        arrive_by = desired_arrival(event_time, early) if event_time is not None else None
        drive_dep = suggested_departure(
            event_time,
            desired_arrival_offset_minutes=early,
            parking_or_walk_minutes=parking,
            drive_duration_seconds=estimate.duration_seconds,
        ) if event_time is not None else None

        envelope["drive"] = {
            "duration_seconds": estimate.duration_seconds,
            "distance_meters": estimate.distance_meters,
            "provider": estimate.provider,
            "routing_preference": estimate.routing_preference,
            "departure_time_used": iso_utc(used_departure),
        }
        envelope["iteration"] = {
            "count": iterations,
            "bounded": True,
            "max": MAX_DEPARTURE_ITERS,
        }
        envelope["last_successful_estimate_at"] = iso_utc(now)
        if arrive_by is not None:
            fields = local_fields(arrive_by, tz_name)
            envelope["desired_arrival"] = fields["utc"]
            envelope["desired_arrival_local"] = fields["local"]
        if drive_dep is not None:
            fields = local_fields(drive_dep, tz_name)
            envelope["suggested_departure"] = fields["utc"]
            envelope["suggested_departure_local"] = fields["local"]
            envelope["suggested_departure_display"] = fields["display_local"]

        if event_time is None:
            envelope["status"] = "ok"
            envelope["code"] = "drive_only"
            envelope["explanation"] = (
                "No event time was provided. Drive duration is a leave-now "
                "traffic snapshot, not a suggested departure."
            )
        elif leave_now or (drive_dep is not None and drive_dep <= now):
            likely = now + timedelta(seconds=estimate.duration_seconds + parking * 60)
            likely_fields = local_fields(likely, tz_name)
            late = late_by_seconds(likely, arrive_by) if arrive_by is not None else None
            envelope["status"] = "leave_now"
            envelope["code"] = "departure_passed"
            envelope["explanation"] = (
                "Suggested departure has already passed. Leave-now uses current "
                "traffic. Likely arrival includes the parking/walk planning allowance."
            )
            envelope["likely_arrival"] = likely_fields["utc"]
            envelope["likely_arrival_local"] = likely_fields["local"]
            envelope["late_by_seconds"] = late
        else:
            envelope["status"] = "ok"
            envelope["code"] = "ok"

        self.signals.emit(
            NAVIGATION_ROUTE_READY,
            member_id=member_id,
            city_place_id=place["city_place_id"],
            object_id=event_ref,
            request_id=request_id or f"ready_{place['city_place_id']}",
            payload={
                "surface": "routes.plan",
                "status": envelope["status"],
                "city_place_id": place["city_place_id"],
                "drive_duration_seconds": estimate.duration_seconds,
            },
        )
        return envelope

    def directions_url(self, user: dict, body: dict | None) -> dict:
        body = body or {}
        origin = body.get("origin") if isinstance(body.get("origin"), dict) else {}
        origin_lat = origin_lng = None
        if origin:
            try:
                origin_lat, origin_lng, _ = parse_origin(origin)
            except ValidationError:
                origin_lat = origin_lng = None
        place, _, event_ref = self._resolve_destination(body, sports_feeds=None)
        request_id = str(body.get("request_id") or "").strip() or f"url_{place['city_place_id']}"
        self.signals.emit(
            DIRECTIONS_REQUESTED,
            member_id=user["user_id"],
            city_place_id=place["city_place_id"],
            object_id=event_ref,
            request_id=request_id,
            payload={
                "surface": "directions_url",
                "city_place_id": place["city_place_id"],
                "emits_navigation_started": False,
            },
        )
        url = external_directions_url(
            dest_lat=place["latitude"],
            dest_lng=place["longitude"],
            dest_name=place["name"],
            origin_lat=origin_lat,
            origin_lng=origin_lng,
        )
        return {
            "status": "ok",
            "code": "ok",
            "city_place_id": place["city_place_id"],
            "destination": {
                "city_place_id": place["city_place_id"],
                "name": place["name"],
                "address": place["address"],
            },
            "directions_url": url,
            "emits_navigation_started": False,
            "navigation": self.navigation.capability(),
            "legal_effect": "provenance_only",
        }

    def _resolve_destination(self, body: dict, *, sports_feeds=None) -> tuple[dict, datetime | None, str | None]:
        city_place_id = str(body.get("city_place_id") or "").strip()
        event_ref = (
            str(body.get("external_game_id") or body.get("schedule_event_id") or body.get("event_id") or "")
            .strip() or None
        )
        event_time = parse_event_time(body.get("event_starts_at") or body.get("event_time"))
        place = None
        if sports_feeds is not None and event_ref:
            game = self._find_game(sports_feeds, event_ref)
            if game:
                resolved = self.places.annotate_game(game)
                if not event_time:
                    event_time = parse_event_time(resolved.get("scheduled_start"))
                if resolved.get("city_place_id"):
                    if city_place_id and city_place_id != resolved["city_place_id"]:
                        raise ValidationError(
                            "city_place_id does not match the resolved sports venue",
                            "city_place_mismatch",
                        )
                    city_place_id = resolved["city_place_id"]
        if not city_place_id:
            raise ValidationError("city_place_id is required", "city_place_required")
        place = self.places.get(city_place_id)
        if not place:
            raise NotFoundError("city place not found", "city_place_not_found")
        return place, event_time, event_ref

    @staticmethod
    def _find_game(sports_feeds, event_ref: str) -> dict | None:
        try:
            games = sports_feeds._all_games()
        except Exception:
            return None
        for game in games:
            if event_ref in {
                game.get("external_game_id"),
                game.get("provider_game_id"),
                game.get("source_ref"),
            }:
                return game
        return None

    def _estimate_drive(
        self,
        origin_lat: float,
        origin_lng: float,
        place: dict,
        event_time: datetime | None,
        early: int,
        parking: int,
        now: datetime,
    ):
        dest_lat = float(place["latitude"])
        dest_lng = float(place["longitude"])
        guess = timedelta(minutes=30)
        if event_time is None:
            estimate = self.provider.compute_drive(
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
                departure_time=now,
            )
            return estimate, 1, now, False

        arrive_by = desired_arrival(event_time, early)
        trial = arrive_by - timedelta(minutes=parking) - guess
        leave_now = trial <= now
        if leave_now:
            estimate = self.provider.compute_drive(
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
                departure_time=now,
            )
            return estimate, 1, now, True

        used = trial
        estimate = None
        iterations = 0
        for _ in range(MAX_DEPARTURE_ITERS):
            iterations += 1
            estimate = self.provider.compute_drive(
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
                departure_time=used,
            )
            nxt = suggested_departure(
                event_time,
                desired_arrival_offset_minutes=early,
                parking_or_walk_minutes=parking,
                drive_duration_seconds=estimate.duration_seconds,
            )
            if nxt <= now:
                return estimate, iterations, used, True
            if abs((nxt - used).total_seconds()) <= CONVERGE_SECONDS:
                used = nxt
                break
            used = nxt
        return estimate, iterations, used, False

    def _base(
        self, place, origin_label, early, parking, tz_name, event_time, event_ref, nav,
    ) -> dict:
        event_fields = local_fields(event_time, tz_name) if event_time else None
        return {
            "status": "hold",
            "code": "hold",
            "city_place_id": place["city_place_id"],
            "destination": {
                "city_place_id": place["city_place_id"],
                "name": place["name"],
                "address": place["address"],
                "timezone": place["timezone"],
            },
            "event": {
                "object_id": event_ref,
                "starts_at": event_fields["utc"] if event_fields else None,
                "starts_at_local": event_fields["local"] if event_fields else None,
                "display_local": event_fields["display_local"] if event_fields else None,
                "timezone": tz_name,
                "date_kind": "event_local",
            } if event_time or event_ref else None,
            "allowances": {
                "label": "planning allowances",
                "desired_arrival_offset_minutes": early,
                "parking_or_walk_minutes": parking,
            },
            "origin": {
                "label": origin_label,
                "source": "client_coordinates",
            },
            "desired_arrival": None,
            "suggested_departure": None,
            "drive": None,
            "iteration": None,
            "last_successful_estimate_at": iso_utc(self._last_successful_estimate_at),
            "explanation": None,
            "navigation": nav,
            "legal_effect": "provenance_only",
        }

    @staticmethod
    def _hold(envelope: dict, code: str, message: str, *, provider_kind: str | None = None) -> dict:
        envelope["status"] = "hold"
        envelope["code"] = code
        envelope["error"] = message
        envelope["explanation"] = message
        envelope["suggested_departure"] = None
        envelope["drive"] = None
        if provider_kind:
            envelope["provider_error_class"] = provider_kind
        return envelope
