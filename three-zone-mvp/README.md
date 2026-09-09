# Three-Zone control-plane MVP

A runnable vertical slice of the Three-Zone event-to-media machine:

```text
event inventory → rights + production clearance → live state → playback lease → replay/archive
```

The control plane owns the event, rights version, zone, production assignment,
entitlement decision, audit trail, socket notifications, and replay lifecycle.
The local demo uses a generated MP4 as the media adapter (`TZ_LIVE_MEDIA_PROVIDER=demo`).
Cloudflare Stream is the first real hosted rail (signed HLS behind the same PDP).
See [RUN_TONIGHT.md](RUN_TONIGHT.md) for provision, OBS/Larix, webhooks, viewer
heartbeats, settlement manifests, troubleshooting, and
`python scripts/live_readiness.py` / `GET /api/ops/live-readiness` before flipping
`TZ_LIVE_MEDIA_PROVIDER=cloudflare`. Member-network uploads use
`TZ_UGC_MEDIA_PROVIDER=fake` (or `cloudflare` for Stream TUS/clips). Mux is a later
empty seam on the live-rail provider interface.

## Run it

Python 3.12+ and (optionally) FFmpeg for the local video signal. Only the
`websockets` package is required by the application.

```bash
cd three-zone-mvp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Open <http://127.0.0.1:8000> for the member site (sign in or create an account).

Open <http://127.0.0.1:8000/ops> for the operator/owner control plane.

Sign in with username and password. Seeded local accounts (override with `TZ_SEED_PASSWORD_*`):

| Username | Password | Role | Lands on |
| --- | --- | --- | --- |
| `demo-viewer` | `change-me-viewer-local` | member | `/` |
| `demo-worker` | `change-me-worker-local` | operator | `/ops` |
| `demo-owner` | `change-me-owner-local` | owner | `/ops` |

Members can also **Create account** on `/`. That always creates a viewer. Staff accounts are not self-serve. From `/ops` use **Member site**; signed-in staff on `/` see **Control plane**.

The member site is also the sports network: **Watch it. Save it. Clip it. Share it.**

Signed-in members can publish photos and short clips, upload a full game as an
immutable source asset, trim a moment in Studio (90 seconds max), and share the
derived clip on For You / Following / Local feeds. Full games stay private and
pending verification until a worker reviews them. Game-derived clips keep a
**Three-Zone Game Clip** provenance label and a **Watch Full Game** link when
the viewer is authorized.

Direct upload never sends large video or photo bytes through the application
server. Full games get a resumable TUS URL; short clips use Cloudflare Stream
`direct_upload` (`uploadURL`); photos use a separate object-storage adapter
(presigned PUT). Local demo and CI use `TZ_LIVE_MEDIA_PROVIDER=demo`,
`TZ_UGC_MEDIA_PROVIDER=fake`, and `TZ_PHOTO_STORAGE=fake`. Cloudflare Stream is
opt-in for **video only**. `TZ_MEDIA_PROVIDER=fake` still maps to UGC fake + live demo;
`TZ_MEDIA_PROVIDER=cloudflare` selects Cloudflare for both rails.

Feed ranking is chronological (`published_at DESC, post_id DESC`). It is not
machine learning.

### Fake-provider local loop

1. Sign in as a member on `/`.
2. Create → Full Game, fill metadata, check the rights attestation, submit.
3. The browser completes the fake provider upload (metadata only). Wait until
   the UI says **Game ready**.
4. Open the game from Profile → Games, set start/end in Studio (for example 0
   and 20), render and publish.
5. The feed shows **Three-Zone Game Clip** and **Watch Full Game**.

The site has three tiers:

| Tier | Account | Capability |
| --- | --- | --- |
| Member site | `demo-viewer` | Midwest entitlement, live and replay playback |
| Back worker side | `demo-worker` | All zones, lifecycle controls, rights revoke/restore, ingest credential issue, audit access |
| Owner side | `demo-owner` | Everything the worker can do, plus the owner back portal that prints/exports every single thing in the site |

The **owner back portal** (`GET /api/owner/inventory`, surfaced in the Owner
panel) prints a complete, page-ready report and downloads a full JSON export:
the tier/capability map, every route, all users, every event with its full
rights version history (including revoked versions), analytics, and the complete
audit log.

**Three Zone Mastery** (`THREE_ZONE_MASTERY.md`, Owner → Mastery, or
`/three-zone-mastery`) is the printable plain-English map of every engine, API,
connection, Treasure verification path, and the XRPL blockchain publication
chain. Print it from the owner sidebar.

The initial inventory contains three Midwest live examples (distinct production
modes, one on an active backup feed), a cleared (green) event, a replay, and
West/East inventory so the zone and lifecycle model is visible immediately.

Run a second copy without touching the default database:

```bash
TZ_ALLOWED_ORIGINS=http://127.0.0.1:18000 \
TZ_DATABASE_PATH=data/smoke.sqlite3 \
python run.py --http-port 18000 --ws-port 18765
```

Container run (the image refuses the demo secret, so provide real ones):

```bash
docker build -t three-zone-mvp .
docker run --rm -p 8000:8000 -p 8765:8765 \
  -e TZ_TOKEN_SECRET="replace-with-a-random-32-plus-character-secret" \
  -e TZ_MEDIA_SERVICE_KEY="replace-with-a-separate-32-plus-character-key" \
  -e TZ_ALLOWED_ORIGINS="http://localhost:8000" \
  three-zone-mvp
```

## The demo path

1. Open `/`, create a member account or sign in as `demo-viewer` / `change-me-viewer-local`.
2. Use Live, Schedules, and Archives; open `Lincoln Freshman Basketball`.
3. Sign out. Open `/ops` and sign in as `demo-owner` / `change-me-owner-local`.
4. Use the left sidebar: Catalog, Player, Operations (create event, controls, schedule, audit), Owner inventory.
5. Open **Member site**, then **Control plane** to move between the two sides.

## What is implemented

- SQLite-backed event, rights, user, and append-only audit state.
- Lifecycle `scheduled → gray → yellow → green → live → replay → archive` with
  guards that require active, version-aligned rights and a ready production path
  (a fresh heartbeat) before `green` or `live`.
- Rights objects with version, territory, destination, package, live/replay
  windows, authority, source reference, revocation, and archive retention.
- Viewer entitlement checks: account state, subscription, zone, package,
  destination, status, and time window.
- Short-lived HMAC session tokens, playback leases, and event/source-scoped
  ingest tokens; wrong token types and tampered tokens are rejected.
- Playback authorization delivered as an HTTP-only, event-path cookie; the media
  URL never carries a bearer token.
- Media validation on every media request, so a stale lease or revoked/re-versioned
  rights object returns `403`.
- Separate WebSocket process for event state, feed heartbeat, lease-renewal
  attempts, and rights-revocation broadcasts, fed by a SQLite transactional outbox.
- WebSocket origin allowlist, session-token validation through
  `Sec-WebSocket-Protocol`, max message size, per-connection message rate limit,
  per-IP connection limit, ping/pong timeout, and clean shutdown.
- Exact-origin CORS with credentials, strict security headers, a locked-down CSP,
  no-store API responses, bounded request bodies, and no secrets in logs or URLs.
- Primary/backup ingest heartbeat with timeout-driven failover and automatic
  return to primary; an encoder-side example in `scripts/ingest_heartbeat.py`.

## HTTP surface

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness check |
| `GET` | `/api/config` | Public client configuration; no secrets |
| `POST` | `/api/auth/demo-login` | Demo-only identity exchange |
| `GET` | `/api/me` | Current signed session identity |
| `GET` | `/api/events` | Event catalog; viewer results are zone constrained |
| `POST` | `/api/events` | Operator creates an event and its initial rights object |
| `GET` | `/api/events/{event_id}` | One event plus non-sensitive access result |
| `POST` | `/api/events/{event_id}/playback-session` | Rights + entitlement check and short lease |
| `POST` | `/api/events/{event_id}/transition` | Operator lifecycle transition |
| `POST` | `/api/events/{event_id}/score` | Operator/producer scoreboard update |
| `POST` | `/api/events/{event_id}/rights/revoke` | Versioned emergency rights block |
| `POST` | `/api/events/{event_id}/rights/restore` | Recovery using a new rights version |
| `POST` | `/api/events/{event_id}/ingest-token` | Operator issues an event/source-scoped credential |
| `POST` | `/api/events/{event_id}/ingest/heartbeat` | Encoder reports primary/backup health |
| `POST` | `/api/events/{event_id}/media/end` | Managed media callback turns live into replay |
| `POST` | `/api/leases/validate` | Media-service validation with a separate service key |
| `GET` | `/api/analytics` | Basic inventory and socket metrics |
| `GET` | `/api/audit` | Operator-only append-only audit view |
| `GET` | `/api/owner/inventory` | Owner-only back portal: prints/exports every part of the site |
| `POST` | `/api/events/{event_id}/media/provision` | Operator binds one hosted live input (key returned once) |
| `POST` | `/api/events/{event_id}/media/rotate-key` | Operator rotates ingest key (returned once) |
| `POST` | `/api/events/{event_id}/media/sync` | Provider status, replay readiness, analytics snapshot |
| `GET` | `/api/events/{event_id}/media/status` | Hosted input status without keys |
| `GET` | `/api/events/{event_id}/settlement-manifest` | Session digests, Merkle root, XRPL enqueue |
| `POST` | `/api/media/webhooks/cloudflare` | Cloudflare/demo webhook (shared secret) |
| `POST` | `/api/events/{event_id}/view-sessions` | Authenticated viewer starts measurement |
| `POST` | `/api/view-sessions/{id}/heartbeat` | Viewer heartbeat (not operator-only) |
| `POST` | `/api/view-sessions/{id}/end` | Close a view session |
| `GET` | `/api/properties/{id}/settlements` | Property-scoped settlements |
| `POST` | `/api/properties/{id}/settlements/{sid}/verify` | MATCH / MISMATCH / INCOMPLETE / PENDING_PUBLICATION |
| `GET` | `/api/network/feed` | For You / Following / Local sports feed |
| `POST` | `/api/network/uploads` | One-time direct-upload contract (no provider token) |
| `POST` | `/api/network/games` | Submit a full-game source asset |
| `POST` | `/api/network/clips` | Persist a Studio clip definition |
| `GET` | `/api/network/review` | Worker review queue |
| `GET` | `/api/network/evidence/{type}/{id}` | Owner evidence bundle |
| `GET` | `/demo/media/{event_id}.mp4` | Lease-gated local demo media |
| `GET` | `/vendor/hls.min.js` | Pinned hls.js 1.5.x |

The event socket is `ws://127.0.0.1:8765/ws/events/{event_id}` in the default
run. The browser sends the session token in the WebSocket subprotocol list, and
the server checks `Origin` against `TZ_ALLOWED_ORIGINS` before admitting it.

## Security boundary

The player is not the authority. It receives a short-lived authorization only
after Three-Zone evaluates the current event and rights state, and the same
decision is repeated by the media route. A socket notification improves
revocation speed; it is not the only enforcement point. `backend/demo_media.py`
is the replacement seam, while `ControlPlane.validate_lease()` is the contract a
managed media proxy must call before serving or packaging content.

See [SECURITY.md](SECURITY.md) for the socket threat model and production launch
gates and [config.example.env](config.example.env) for configuration.

## Tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q backend run.py
```

The tests cover live lease issuance, zone denial, lifecycle ordering, automatic
replay transition, rights-revocation invalidation, version-bound lease rejection,
event/source-scoped ingest credentials, media-service-key enforcement, token
tamper rejection, the hosted media rail (fake provider only), viewer sessions,
Merkle settlement, and honest demo XRPL receipts.

## Scope note

This is the executable control-plane pilot, not a claim that a local process is
ready for national broadcast traffic. Before a public launch, add OIDC, TLS,
Postgres, a durable event bus, managed contribution/packaging/CDN, key
management, observability, load tests, disaster recovery, a privacy review for
youth content, and counsel-reviewed rights workflows. The code makes those
ownership boundaries explicit so a first pilot can prove the critical loop:

```text
camera/encoder signal → authorized event → family playback → automatic replay
```
