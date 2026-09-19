"""Server-side Google Routes computeRoutes client.

Driving uses departureTime, never arrivalTime.
https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes

Missing key or provider error fail closed. This module never invents a duration.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.distanceMeters"
DEFAULT_TIMEOUT = 8.0
USER_AGENT = "three-zone-getting-there/1.0"


class RoutesProviderError(Exception):
    def __init__(self, kind: str, message: str = "", status: int | None = None):
        super().__init__(message or kind)
        self.kind = kind
        self.status = status


class NotConfiguredError(RoutesProviderError):
    def __init__(self):
        super().__init__(
            "not_configured",
            "GOOGLE_MAPS_API_KEY / GOOGLE_ROUTES_API_KEY is not set",
        )


@dataclass(frozen=True)
class DriveEstimate:
    duration_seconds: int
    distance_meters: int | None
    departure_time: datetime
    routing_preference: str
    provider: str = "google_routes"


def parse_duration_seconds(raw) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if text.endswith("s") and text[:-1].replace(".", "", 1).isdigit():
        return int(float(text[:-1]))
    if text.isdigit():
        return int(text)
    return None


class GoogleRoutesProvider:
    """Thin urllib client. Secrets are never logged or returned."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        opener=None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self._opener = opener
        self._sleep = sleeper

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def __repr__(self) -> str:
        return f"GoogleRoutesProvider(configured={self.configured!r})"

    def compute_drive(
        self,
        *,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        departure_time: datetime,
    ) -> DriveEstimate:
        if not self.configured:
            raise NotConfiguredError()
        if departure_time.tzinfo is None:
            departure_time = departure_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        dep_utc = departure_time.astimezone(timezone.utc)
        body: dict = {
            "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}},
            "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lng}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "languageCode": "en-US",
            "units": "IMPERIAL",
        }
        # Routes API rejects a past departureTime. Leave-now omits the field
        # so Google evaluates current traffic.
        if dep_utc > now + timedelta(seconds=15):
            body["departureTime"] = dep_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            ROUTES_URL,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": FIELD_MASK,
                "User-Agent": USER_AGENT,
            },
        )
        try:
            opener = self._opener or urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl.create_default_context())
            )
            with opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            _ = exc.read()
            raise RoutesProviderError("provider_error", "routes provider HTTP error", exc.code) from None
        except urllib.error.URLError as exc:
            raise RoutesProviderError("provider_error", "routes provider unreachable") from exc
        except TimeoutError:
            raise RoutesProviderError("timeout", "routes provider timeout") from None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RoutesProviderError("bad_response", "routes provider returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise RoutesProviderError("bad_response", "routes provider returned a non-object")
        routes = data.get("routes")
        if not isinstance(routes, list) or not routes:
            raise RoutesProviderError("bad_response", "routes provider returned no routes")
        first = routes[0] if isinstance(routes[0], dict) else {}
        duration = parse_duration_seconds(first.get("duration"))
        if duration is None or duration < 0:
            raise RoutesProviderError("bad_response", "routes provider omitted duration")
        distance = first.get("distanceMeters")
        try:
            distance_m = int(distance) if distance is not None else None
        except (TypeError, ValueError):
            distance_m = None
        used = dep_utc if "departureTime" in body else now
        return DriveEstimate(
            duration_seconds=duration,
            distance_meters=distance_m,
            departure_time=used,
            routing_preference="TRAFFIC_AWARE",
        )
