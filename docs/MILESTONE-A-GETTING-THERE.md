# Milestone A — Getting There

Product promise: *Find something worth doing. Know when to leave. Get there without leaving THREEZONE.*

Navigation belongs inside **City**. Sports is one vertical. This document is the backend contract for Milestone A only. It does not implement Milestone B turn-by-turn, Plan My Night (D), or merchant dashboards.

Plane: Three-Zone **Runtime / City**. Spec alignment: fail closed (§2.7), dates labeled (§2.1), versioned evidence only.

This repository is the **Render backend** (`three-zone-mvp/`) plus Moten control-plane sources. Capacitor and the member product UI live in the **Lovable Member Gateway** (separate). This milestone does not create a member portal.

## Status

| Gate | Status | Evidence |
| --- | --- | --- |
| BUILT | **yes** | Member city/route endpoints, `RoutePlanningService`, `NavigationService` stub, city place seed |
| TESTED WITH FIXTURES | **yes** | `three-zone-mvp/tests/test_getting_there.py` (departure math, past deadline, missing coords, mock provider failure, HTTP auth) |
| VERIFIED WITH LIVE PROVIDER | **no** | No live `computeRoutes` call was made in this change. Fixtures only. |
| VERIFIED ON PHYSICAL DEVICE | **no** | Out of scope for this backend. No Capacitor project in-repo. |
| PRODUCTION CONFIGURED | **no** | Env names are documented. Secret values are not present in git. Render dashboard must supply keys. |
| PRODUCTION VERIFIED | **no** | Not claimed. |

## Architecture findings (inspect)

| Surface | Finding |
| --- | --- |
| Capacitor | Not in this repo. Member UI is Lovable (`app.3zonesports.com`). |
| API | Python stdlib `http.server` in `three-zone-mvp/backend/http_server.py`. Member auth = Bearer session or `tz_member_session`. |
| City places | Did not exist. Added `city_places` / `city_place_links` / `city_signals`. Canonical id prefix `plc_`. |
| Sports | BALLDONTLIE snapshots now annotated with `city_place_id` when the home team or venue alias matches. |
| Maps / Routes | No prior Google Maps or geocoding client. Server-side Routes only. |
| Geocoding | Not previously present. Origin is **lat/lng + optional label**. Address-only origin fails closed (`origin_coordinates_required`). |

## Endpoints (member auth)

All require `Authorization: Bearer <session_token>` (or same-origin member cookie). Cross-origin Lovable must use Bearer.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/member/city/places` | Active canonical places (`?vertical=sports`) |
| GET | `/api/member/city/places/{city_place_id}` | One place (name, address, timezone, coordinates) |
| POST | `/api/member/city/routes/plan` | Canonical traffic-aware drive plan. Emits `directions_requested`; emits `navigation.route_ready` only when a usable route is returned |
| POST | `/api/member/getting-there` | Lovable Member Gateway alias of `city/routes/plan` (same handler) |
| POST | `/api/member/route-plan` | Lovable fallback alias of `city/routes/plan` (same handler) |
| POST | `/api/member/city/directions-url` | External Google Maps dir URL. Emits `directions_requested` only. **Does not** emit `navigation.started` |
| GET | `/api/member/city/navigation/capability` | `{ native: false }` Milestone B stub |

`GET /api/health` includes `getting_there` (configured flag, place count, `last_successful_estimate_at`) with **no secrets**.

`GET /api/config` includes `getting_there.routes_configured` and allowance defaults.

Sports member snapshots (`/api/member/sports*`) and `/api/member/schedules` attach `city_place_id` / `city_place` when resolvable. That is an API annotation, not a portal.

## Plan request

```json
{
  "city_place_id": "plc_kc_arrowhead",
  "origin": { "lat": 38.9822, "lng": -94.6708, "label": "optional" },
  "event_starts_at": "2026-09-20T21:00:00Z",
  "external_game_id": "optional-bdl:nfl:…",
  "desired_arrival_offset_minutes": 10,
  "parking_or_walk_minutes": 10,
  "request_id": "client-dedupe-id"
}
```

Lovable Member Gateway aliases (same planner): `desired_arrival_offset_min`, `parking_walk_min`, `arrive_by` (maps to event time). `origin.address` is accepted only as a label; address-only origin still fails closed (`origin_coordinates_required`) because this host does not geocode.

Gateway-readable response fields (in addition to the canonical names): `drive_minutes` / `duration_minutes`, `suggested_departure` / `leave_at`, `calculated_at`, `leave_now`, `explanation` / `message`, `state` (`ok` | `leave_now` | `unavailable`). Provider unavailable → `status=hold`, `state=unavailable`, null times, no invented minutes.

`city_place_id` is required (or resolved from a sports `external_game_id` that maps to a place). Event time is optional; when present it is labeled `date_kind: event_local` in the place timezone (default `America/Chicago`).

## Formula

Planning allowances (defaults 10 minutes each), not guarantees:

```
desired_arrival     = event_time − desired_arrival_offset
suggested_departure = desired_arrival − parking_or_walk − drive_duration
```

Fixture: **4:00 PM event − 10 early − 10 parking − 25 drive = 3:15 PM**.

Driving calls Google Routes `computeRoutes` with `travelMode=DRIVE`, `routingPreference=TRAFFIC_AWARE`, and **`departureTime` only** (never `arrivalTime`). See [computeRoutes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes).

Bounded iteration (max 3, 45s convergence) re-evaluates `departureTime` for a future suggested departure. If the suggested departure is already past: `status=leave_now`, current-traffic estimate, and an explanation of likely arrival. `last_successful_estimate_at` is set only after a provider duration is received.

**Fail closed:** missing key or provider error → `status=hold`, `suggested_departure=null`, `drive=null`. Times are never invented.

## Signals

Documented in `backend/city/signals.py` (`SIGNAL_VOCABULARY`).

| Signal | Milestone A |
| --- | --- |
| `directions_requested` | Emitted on explicit plan or directions-URL POST |
| `navigation.route_ready` | Emitted only when a usable planning route is returned |
| `navigation.started` | **Forbidden** here |
| `navigation.arrived` | **Forbidden** here |

Dedupe: `event_type + member_id + city_place_id + request_id`. Payloads strip precise coordinates.

## City places

Seeded KC sports anchors (public stadium locations):

| `city_place_id` | Name | Home team |
| --- | --- | --- |
| `plc_kc_arrowhead` | GEHA Field at Arrowhead Stadium | `team_nfl_kc_chiefs` |
| `plc_kc_kauffman` | Kauffman Stadium | `team_mlb_kc_royals` |

Helpers: `CityPlaceService.ensure_seeded()` from `seed_if_empty` / `make_http_server`. Schema in `backend/db.py` (`city_places`, `city_place_links`, `city_signals`). Schedule rows are annotated at read time from location aliases — the `schedule_events` table is not widened.

## Config names (no secret values)

| Name | Role |
| --- | --- |
| `GOOGLE_MAPS_API_KEY` | Shared Maps key (used if no dedicated Routes key) |
| `TZ_GOOGLE_MAPS_API_KEY` | Alias |
| `GOOGLE_ROUTES_API_KEY` | Preferred dedicated Routes key |
| `TZ_GOOGLE_ROUTES_API_KEY` | Alias |

Empty / unset → hold. Do not commit values. Render blueprint lists the two public names with `sync: false`.

## Services

- `RoutePlanningService` — planning, iteration, hold/leave-now
- `NavigationService` — capability stub, `native=false` until Milestone B
- `GoogleRoutesProvider` — server-side `computeRoutes` only

## Out of scope (intentionally not built)

- Turn-by-turn / Navigation SDK
- Plan My Night (D)
- Merchant dashboards
- Member portal UI / Capacitor plugin
- Address geocoding
- Invented ETAs when the provider is down
