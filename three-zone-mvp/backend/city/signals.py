"""City Getting There signal vocabulary and evidence-only emission.

Milestone A may emit only:
  - directions_requested   (explicit member request)
  - navigation.route_ready (usable planning route returned)

Never emit navigation.started or navigation.arrived from planning or web.
Those require native Navigation SDK evidence (Milestone B).

Payloads carry ids, not precise coordinates. Dedupe is unique on
(event_type, member_id, city_place_id, request_id). legal_effect is
provenance_only — this is not a filing date or legal conclusion.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from ..db import dumps

DIRECTIONS_REQUESTED = "directions_requested"
NAVIGATION_ROUTE_READY = "navigation.route_ready"
NAVIGATION_STARTED = "navigation.started"
NAVIGATION_ARRIVED = "navigation.arrived"

MILESTONE_A_EMITTABLE = frozenset({DIRECTIONS_REQUESTED, NAVIGATION_ROUTE_READY})
MILESTONE_A_FORBIDDEN = frozenset({NAVIGATION_STARTED, NAVIGATION_ARRIVED})

SIGNAL_VOCABULARY = {
    DIRECTIONS_REQUESTED: {
        "plane": "City",
        "milestone": "A",
        "when": (
            "Member explicitly requested Getting There planning or an external "
            "directions URL. Requires an authenticated member action."
        ),
        "evidence": "HTTP POST to /api/member/city/routes/plan or /api/member/city/directions-url",
        "emits_in_milestone_a": True,
        "includes_precise_coordinates": False,
    },
    NAVIGATION_ROUTE_READY: {
        "plane": "City",
        "milestone": "A",
        "when": (
            "A usable traffic-aware planning route was returned (status ok or "
            "leave_now) with a provider drive duration. Not emitted on hold, "
            "validation errors, or directions-URL-only responses."
        ),
        "evidence": "Google Routes computeRoutes success recorded server-side",
        "emits_in_milestone_a": True,
        "includes_precise_coordinates": False,
    },
    NAVIGATION_STARTED: {
        "plane": "City",
        "milestone": "B",
        "when": "Native turn-by-turn session actually started on device.",
        "evidence": "Navigation SDK session start — not a planning estimate or maps URL",
        "emits_in_milestone_a": False,
        "includes_precise_coordinates": False,
    },
    NAVIGATION_ARRIVED: {
        "plane": "City",
        "milestone": "B",
        "when": "Native arrival evidence from the Navigation SDK.",
        "evidence": "Navigation SDK arrival — not a planning likely-arrival clock",
        "emits_in_milestone_a": False,
        "includes_precise_coordinates": False,
    },
}

_FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "lat", "lng", "latitude", "longitude", "origin_lat", "origin_lng",
    "destination_lat", "destination_lng", "coords", "coordinate",
    "polyline", "encoded_polyline",
})


class SignalError(Exception):
    """Raised when a signal is forbidden or malformed."""


def _id() -> str:
    return "sig_" + uuid.uuid4().hex[:16]


def _sanitize_payload(payload: dict | None) -> dict:
    clean = {}
    for key, value in (payload or {}).items():
        if str(key).lower() in _FORBIDDEN_PAYLOAD_KEYS:
            continue
        if isinstance(value, dict):
            nested = _sanitize_payload(value)
            if nested:
                clean[key] = nested
            continue
        clean[key] = value
    return clean


def _dedupe_key(event_type: str, member_id: str, city_place_id: str | None, request_id: str) -> str:
    raw = dumps({
        "event_type": event_type,
        "member_id": member_id,
        "city_place_id": city_place_id or "",
        "request_id": request_id,
    })
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


class CitySignalService:
    """Append-only city signals. Fail closed on forbidden types."""

    def __init__(self, db):
        self.db = db

    def emit(
        self,
        event_type: str,
        *,
        member_id: str,
        city_place_id: str | None = None,
        object_id: str | None = None,
        request_id: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        if event_type in MILESTONE_A_FORBIDDEN:
            raise SignalError(
                f"{event_type} is Milestone B native-nav evidence and cannot be "
                "emitted from planning or web"
            )
        if event_type not in MILESTONE_A_EMITTABLE:
            raise SignalError(f"unknown or undocumented city signal: {event_type}")
        if not member_id:
            raise SignalError("member_id is required")
        req = (request_id or "").strip() or ("auto_" + uuid.uuid4().hex[:12])
        safe = _sanitize_payload(payload)
        safe.setdefault("city_place_id", city_place_id)
        safe["event_type"] = event_type
        key = _dedupe_key(event_type, member_id, city_place_id, req)
        existing = self.db.query_one(
            "SELECT signal_id, event_type, recorded_at FROM city_signals WHERE dedupe_key=?",
            (key,),
        )
        if existing:
            return {
                "signal_id": existing["signal_id"],
                "event_type": existing["event_type"],
                "deduped": True,
                "recorded_at": existing["recorded_at"],
            }
        signal_id = _id()
        stamp = time.time()
        self.db.execute(
            "INSERT INTO city_signals(signal_id,event_type,member_id,city_place_id,object_id,"
            "request_id,dedupe_key,payload,recorded_at,legal_effect) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                signal_id, event_type, member_id, city_place_id, object_id, req,
                key, dumps(safe), stamp, "provenance_only",
            ),
        )
        return {
            "signal_id": signal_id,
            "event_type": event_type,
            "deduped": False,
            "recorded_at": stamp,
            "legal_effect": "provenance_only",
        }

    def vocabulary(self) -> dict:
        return {
            "milestone": "A",
            "emittable": sorted(MILESTONE_A_EMITTABLE),
            "forbidden_until_native": sorted(MILESTONE_A_FORBIDDEN),
            "signals": SIGNAL_VOCABULARY,
            "rules": {
                "evidence_only": True,
                "precise_coordinates": False,
                "dedupe": "event_type+member_id+city_place_id+request_id",
                "legal_effect": "provenance_only",
            },
        }
