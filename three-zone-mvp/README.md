# Three-Zone control-plane MVP

A runnable vertical slice of the Three-Zone event-to-media machine:

```text
event inventory → rights + production clearance → live state → playback lease → replay/archive
```

The control plane owns the event, rights version, zone, production assignment,
entitlement decision, audit trail, socket notifications, and replay lifecycle.
The local demo uses a generated MP4 as the media adapter. A production
deployment replaces that adapter with a managed SRT contribution, transcoder,
packager, object store, and CDN.

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

Open <http://127.0.0.1:8000>.

| Account | Capability |
| --- | --- |
| `demo-viewer` | Midwest entitlement, live and replay playback |
| `demo-admin` | All zones, lifecycle controls, rights revoke/restore, ingest credential issue, audit access |

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

1. Sign in as `demo-viewer`.
2. Filter to **midwest**; open `Lincoln Freshman Basketball` (live).
3. The browser requests a playback lease, receives an event-scoped HTTP-only
   cookie, opens the event socket (token in the WebSocket subprotocol, not the
   URL), and loads the local managed-media adapter.
4. Sign in as `demo-admin` in another tab to move `Lakeside Volleyball` through
   the operator controls, issue an ingest token, send a heartbeat, and revoke
   rights on a live event. Socket subscribers receive `rights.revoked`, and the
   media endpoint rejects the existing lease on its next request.

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
| `GET` | `/demo/media/{event_id}.mp4` | Lease-gated local demo media |

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
event/source-scoped ingest credentials, media-service-key enforcement, and token
tamper rejection.

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
