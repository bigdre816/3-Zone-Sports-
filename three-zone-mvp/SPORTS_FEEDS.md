# Sports data feeds (Phase 1)

Server-side **BALLDONTLIE** adapters publish NFL, MLB, and NBA score/schedule
facts through Three-Zone `/api/public/scores` and `/api/member/scores`.

This is **not** streaming, media rights, or `LIVE_PUBLIC`. A score row is never
a watch lease.

## Configuration

Set `BALLDONTLIE_API_KEY` on the host (Render dashboard secret). Leave it empty
in `config.example.env`. Missing/blank keys fail closed as `freshness:
not_configured` with empty `games` — **no demo scores**.

Durable last-good snapshots live in `sports_feed_snapshots` on the same SQLite
file (`TZ_DATABASE_PATH`, Render disk `/data/three_zone.sqlite3`) or Postgres
when `TZ_DATABASE_URL` is set.

## What is LIVE AND VERIFIED vs mocked

| Surface | Offline / CI | Needs Render secret |
| --- | --- | --- |
| Normalized API shape, freshness, Chicago display | Mocked provider fixtures | — |
| Fail-closed `not_configured` | Default (empty key) | — |
| Real NFL/MLB/NBA scores | — | `BALLDONTLIE_API_KEY` on service `3-Zone-Sports--1` |
| College | **NOT CONFIGURED** | Not a BALLDONTLIE product |
| High school / youth | **NOT CONFIGURED** | Existing Three-Zone catalog/CSV/live events |

## Entitlement gaps (college / HS)

BALLDONTLIE hosts used here: `https://api.balldontlie.io` with `/nfl/v1`,
`/mlb/v1`, and `/nba/v1` (NBA falls back to `/v1`). College football,
college basketball, and high-school athletics are **not configured**. They
remain on:

- Kansas City school/team seed catalog
- Operator CSV schedule import (`/api/admin/schedules/upload`)
- Control-plane live events and rights leases

The API repeats this under `gaps.college` and `gaps.high_school`.

## Member UI

The member portal is `three-zone-mvp/backend/static` on the same host. There is
**no** separate Lovable sports repo in this activation. The browser only calls
`/api/member/scores*`. It never calls `api.balldontlie.io`.

## Later phases (not in this change)

- Full member signal engine and ZIP B2B exports
- PredictHQ
- Purchasing additional BALLDONTLIE subscriptions
