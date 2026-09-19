"""HTTP bootstrap for THREEZONE City Getting There (milestone A).

The main server intentionally stays small and stdlib-only. This module attaches
City routes to its handler at process bootstrap so milestone A can ship without
forking the established member/session dispatch path.
"""
from __future__ import annotations

import re

from .city_route_planning import (
    CityRepository,
    GoogleRoutesClient,
    RoutePlanningError,
    RoutePlanningService,
    _parse_datetime,
)

_CITY_ROUTES = [
    ("GET", re.compile(r"^/city$"), "h_city_page", "none"),
    ("GET", re.compile(r"^/city\.(?P<asset>css|js)$"), "h_city_asset", "none"),
    ("GET", re.compile(r"^/api/member/city/config$"), "h_city_config", "member"),
    ("GET", re.compile(r"^/api/member/city/planning-anchor$"), "h_city_planning_anchor", "member"),
    ("GET", re.compile(r"^/api/member/city/places/(?P<city_place_id>cp_[A-Za-z0-9_-]+)$"), "h_city_place_get", "member"),
    ("GET", re.compile(r"^/api/member/city/events/(?P<city_event_id>ce_[A-Za-z0-9_-]+)$"), "h_city_event_get", "member"),
    ("POST", re.compile(r"^/api/member/city/getting-there$"), "h_city_getting_there", "member"),
    ("POST", re.compile(r"^/api/admin/city/places$"), "h_city_place_upsert", "operator"),
    ("POST", re.compile(r"^/api/admin/city/events$"), "h_city_event_upsert", "operator"),
]


def _repo(handler):
    return CityRepository(handler.cp.db)


def _send_city_error(handler, exc: RoutePlanningError) -> None:
    handler._send_json(exc.status, {"error": str(exc), "code": exc.code})


def h_city_page(self, p, b, u):
    self._serve_static("city.html")


def h_city_asset(self, p, b, u):
    asset = p.get("asset")
    if asset not in ("css", "js"):
        self._send_json(404, {"error": "not found", "code": "not_found"})
        return
    self._serve_static(f"city.{asset}")


def h_city_config(self, p, b, u):
    client = GoogleRoutesClient()
    self._send_json(200, {
        "route_planning": {
            "provider": "google_routes",
            "configured": client.configured,
            "traffic_aware": True,
            "max_requests_per_calculation": 2,
        },
        "native_navigation": {
            "available": False,
            "reason": "native_navigation_not_integrated",
        },
        "location": {
            "discovery_precision": "selected_city_or_approximate",
            "getting_there_precision": "one_time_precise_after_explicit_action_or_manual_origin",
            "continuous_location": "not_started_in_milestone_a",
        },
    })


def h_city_planning_anchor(self, p, b, u):
    """Resolve an already-authorized source event to a canonical City anchor.

    Sports/provider venue names are not auto-matched here. The anchor only
    exists after an operator-created city_event explicitly binds a source and
    source_event_id to a canonical city_place_id.
    """
    qs = self._qs()
    source = str(qs.get("source") or "").strip()
    source_event_id = str(qs.get("source_event_id") or "").strip()
    if not source or not source_event_id or len(source) > 64 or len(source_event_id) > 160:
        self._send_json(400, {"error": "source and source_event_id are required", "code": "source_event_required"})
        return
    row = self.cp.db.query_one(
        "SELECT city_event_id FROM city_events WHERE source=? AND source_event_id=? "
        "ORDER BY last_verified_at DESC LIMIT 1",
        (source, source_event_id),
    )
    if not row:
        self._send_json(200, {
            "anchor": None,
            "reason": "canonical_place_not_mapped",
            "source": source,
            "source_event_id": source_event_id,
        })
        return
    try:
        detail = _repo(self).event_detail(row["city_event_id"])
    except RoutePlanningError as exc:
        _send_city_error(self, exc)
        return
    self._send_json(200, {
        "anchor": {
            "city_event_id": detail["event"]["city_event_id"],
            "city_place_id": detail["place"]["city_place_id"],
            "event": detail["event"],
            "place": detail["place"],
        }
    })


def h_city_place_get(self, p, b, u):
    try:
        self._send_json(200, {"place": _repo(self).get_place(p["city_place_id"])})
    except RoutePlanningError as exc:
        _send_city_error(self, exc)


def h_city_event_get(self, p, b, u):
    try:
        self._send_json(200, _repo(self).event_detail(p["city_event_id"]))
    except RoutePlanningError as exc:
        _send_city_error(self, exc)


def h_city_getting_there(self, p, b, u):
    try:
        service = RoutePlanningService(self.cp.db, routes_client=GoogleRoutesClient())
        result = service.estimate_getting_there(b or {})
        self._send_json(200, result)
    except RoutePlanningError as exc:
        _send_city_error(self, exc)


def h_city_place_upsert(self, p, b, u):
    body = b or {}
    try:
        place = _repo(self).match_or_create_place(
            city_place_id=str(body.get("city_place_id") or ""),
            name=str(body.get("name") or ""),
            place_type=str(body.get("type") or "venue"),
            latitude=body.get("latitude"),
            longitude=body.get("longitude"),
            address=str(body.get("address") or ""),
            source=str(body.get("source") or "threezone"),
            source_id=(str(body.get("source_id")) if body.get("source_id") is not None else None),
            neighborhood=str(body.get("neighborhood") or ""),
            provenance=body.get("provenance") if isinstance(body.get("provenance"), dict) else None,
            rights_use_class=str(body.get("rights_use_class") or "unknown"),
        )
        self._send_json(200, {"place": place})
    except RoutePlanningError as exc:
        _send_city_error(self, exc)


def h_city_event_upsert(self, p, b, u):
    body = b or {}
    timezone_name = str(body.get("timezone") or "America/Chicago")
    starts_at = body.get("starts_at")
    try:
        if isinstance(starts_at, str) and starts_at.strip():
            starts_at = _parse_datetime(starts_at, default_timezone=timezone_name)
        event = _repo(self).upsert_event(
            city_event_id=str(body.get("city_event_id") or ""),
            title=str(body.get("title") or ""),
            city_place_id=str(body.get("city_place_id") or ""),
            starts_at=starts_at,
            timezone_name=timezone_name,
            source=str(body.get("source") or "threezone"),
            source_event_id=(str(body.get("source_event_id")) if body.get("source_event_id") is not None else None),
            status=str(body.get("status") or "scheduled"),
        )
        self._send_json(200, {"event": event})
    except RoutePlanningError as exc:
        _send_city_error(self, exc)


def install_city_http(handler_cls) -> None:
    """Attach City routes once while preserving established auth dispatch."""
    if getattr(handler_cls, "_threezone_city_installed", False):
        return
    for name, func in {
        "h_city_page": h_city_page,
        "h_city_asset": h_city_asset,
        "h_city_config": h_city_config,
        "h_city_planning_anchor": h_city_planning_anchor,
        "h_city_place_get": h_city_place_get,
        "h_city_event_get": h_city_event_get,
        "h_city_getting_there": h_city_getting_there,
        "h_city_place_upsert": h_city_place_upsert,
        "h_city_event_upsert": h_city_event_upsert,
    }.items():
        setattr(handler_cls, name, func)
    handler_cls.routes = list(_CITY_ROUTES) + list(handler_cls.routes)
    handler_cls._threezone_city_installed = True
