# Three Zone Mastery

**The complete plain-English map of everything that lives in this system.**

This is not a marketing page. It is the owner's master document: the vision, every engine, every API, every connection, every table, every token, every cookie, every audit event, AI sovereignty (default OFF), private live capture L1B (default OFF), Treasure verification, Moten evidence handoffs, and the XRPL publication chain. Print it from the owner back portal (Owner → Mastery → Print this guide), or open `/three-zone-mastery` and print the page.

If a piece of the live site is currently running, the Owner → Inventory report prints the **live numbers**. This document prints the **meaning** of those numbers.

Honest defaults that matter for production claims:

- `THREEZONE_AI_ENABLED=false` — AI Gateway process kill switch. Product HTTP AI routes exist but return `ai_disabled` unless this is explicitly true. V0 sports vision is **library-only** (no HTTP).
- `THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED=false` — L1B private live sessions are operator-only and stay private (no Restream, no public distribution, no AI).
- Moten outbox `status=delivered` with a Moten body like `{"accepted": true}` means **receiver acceptance of an evidence packet**, not three-human Moten AI review.
- Lineage `approve` is a **local / member-gated** provenance write — not Moten R1/R2/signer.
- Gray-gate automation and Treasure AI packet ownership are still **open** design questions.

---

## Purpose and how to print

1. Sign in on `/ops` as `demo-owner` / `change-me-owner-local` (or your real owner account).
2. Open the **Owner** dropdown in the left sidebar.
3. Click **Mastery**.
4. Click **Print this guide**. Your browser print dialog will produce a black-on-white paper copy.
5. Separately, Owner → Inventory → **Print everything** prints the live users, events, rights versions, analytics, and audit log.

The source file of this article is `three-zone-mvp/THREE_ZONE_MASTERY.md`. The printable HTML renderer is `backend/mastery.py` (h1–h4, paragraphs, lists, tables, fences, `code`, **bold** only — no HTML in the markdown source).

---

## What this repository actually is

The git repository is named **3-Zone-Sports-**. It holds two related products, plus a leftover clock page.

**Product A — Moten IP & Invention Control Plane** (`index.html` at the repo root). A browser-only confidential control surface for invention work. It uses local storage. It is a prototype of the Moten master specification: research registry, invention ledger, disclosure firewall, filing calendar, counsel workbench, evidence hashes, default-deny access, AI gateway (in Moten IP), rights registry, lease simulation, socket simulation, ingest, revocation, discovery, measurement, settlement, partner adapters, WORM export, and drills. It does **not** serve live sports video. It is the **IP and policy brain** of the larger idea.

**Product B — Three-Zone control-plane MVP** (`three-zone-mvp/`). A runnable Python server. This is the **event-to-media machine**: catalog, rights, entitlement, playback leases, replay, member site, member network (posts/games/clips), operator console, owner back portal, optional AI Gateway (Y1a/Y1b), optional private live capture (L1B), Treasure verification adapter, Moten evidence outbox, hashed audit chain, and a simulated XRPL publication path. This is what you log into at `/` and `/ops`.

**Leftover —** `timezone-clock.html` is a decorative multi-timezone clock. It is not wired into Three-Zone or Moten.

When this document says "the system," it means Product B unless it explicitly says Moten IP.

The machine in one sentence:

**A camera or encoder may only become a family playback if Three-Zone says the event is real, the rights are active, the viewer is entitled, a short lease is issued, and the media path re-checks that same decision on every byte.**

The loop:

```text
camera / encoder signal
  → authorized event (lifecycle + rights + production heartbeat)
    → family playback (lease + cookie + media re-check)
      → automatic replay
        → archive
          → hashed audit record
            → blockchain (XRPL) publication of the hash, not the private payload
```

Optional side rails (both default OFF in production):

```text
AI Gateway (THREEZONE_AI_ENABLED) → caption / embed / describe / lineage (no vision HTTP)
L1B private live (THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED) → operator-only, never public
Moten outbox → async evidence handoff (accepted = Moten received the packet)
```
---

## Vision and offers

Three-Zone is not "a sports website." It is a **rights-aware distribution machine** for school and community sports, designed so a family can watch what they are entitled to, and so nobody else can.

The Moten invention ledger names six Three-Zone families and six Treasure families. Those are the mechanisms this MVP is proving in software, even when a given family is still a simulation.

### The six Three-Zone invention families

**TZ-01 — Rights-aware distribution router.** Join household relationship, service area, package, rights, territory, device, and destination, then route only to an authorized experience. In this MVP the router is `evaluate_access`: account, subscription, zone, package, destination, lifecycle, and time window.

**TZ-02 — Demand-guided rights acquisition engine.** Join demand to versioned property availability, rights expiry, production readiness, and economics, then emit a ranked opportunity with a human approval gate. This MVP does **not** yet rank acquisition opportunities. It does keep rights versioned and production-gated, which is the constraint side of that engine.

**TZ-03 — Adaptive broadcast orchestration.** Choose ingest, certified producer, or full-service broadcast from rights, feed quality, local capability, cost, and reliability. This MVP implements the **ingest and failover** slice: primary/backup heartbeats, timeout failover, and return to primary. Hosted live rail can be `demo` or `cloudflare`.

**TZ-04 — Rights-bound media object.** Every media derivative should carry territory, window, replay, clips, ads, master, distributor, expiration, and authorization. This MVP binds a lease to `event_id`, `rights_version`, `mode`, and `sub`, then re-validates on the media path. The local MP4 is a stand-in for a packaged object; Cloudflare Stream is the first real hosted rail.

**TZ-05 — Auditable multi-property settlement.** Compute economics from immutable measurement facts and formula versions. This MVP keeps view sessions, heartbeats, settlement manifests, Merkle leaves, and hash-chained audit so settlement later has a reconstructible history. It does **not** compute money payouts.

**TZ-06 — Relationship-based sports discovery graph.** Navigate from family, school, hometown, alumni, conference, or team to rights-aware availability. This MVP has schools, teams, schedules, archives, member network profiles/follows, and a search that only returns authorized catalog items. It is not yet a full relationship graph.

### The six Treasure invention families

Treasure is the **verification and evidence** side. It is not the sports player.

**TR-01 — Reward / evidence separation.** Rewards a bounded activity without rewriting evidence history. Independent ledgers and signed event references. In this MVP, the operational `audit` table and the canonical `audit_events` hash chain are separate from any future reward score.

**TR-02 — Capped score impact with persistent evidence.** Not implemented as a score product here. The principle is already visible: evidence accumulates even when access is denied.

**TR-03 — Multi-activity consistency history.** Canonical audit events keep type, actor, subject, payload hash, and previous hash so different activities stay distinguishable.

**TR-04 — Participant-selected evidence presentation.** Not a member-facing evidence wallet yet. Operator/owner can inspect an audit event and its XRPL receipt without dumping private media. Owner network evidence export (JSON/CSV/HTML) exists for game/clip/post subjects.

**TR-05 — AI-assisted control architecture.** Moten IP's AI gateway is the prototype of tool-only AI under human authority. **Update vs older docs:** Three-Zone now contains an AI Gateway package (`threezone_ai`) and product HTTP routes under `/api/ai/*`. Those routes are **disabled by default** (`THREEZONE_AI_ENABLED` fail-closed). `gateway.run` refuses work when the process kill switch is off; Settings/YAML cannot bypass it. V0 sports vision is a **library only** — no product HTTP, no worker admission, no gateway task. Humans and policy remain the authority. Gray-gate automation that would bind Treasure AI packets to lifecycle clearance is **not owned** yet.

**TR-06 — Anonymous-to-authorized identity transition.** Member login starts as a username/password, then **Treasure verification** issues a time-bounded VERIFIED record before a member session cookie is set. In demo, Treasure is simulated. In production, missing Treasure is fail-closed.

### The Moten IP control plane (root `index.html`)

That browser app is the confidential invention office: command center, research registry with immutable question versions, invention ledger, human contribution capture (AI is tool-only), disclosure firewall (hold/file-first), USPTO filing calendar, counsel workbench, SHA-256 manifests, default-deny access, AI gateway, provisional support matrix, rights registry, policy decision point, short-lived rights leases, live-socket admission simulation, ingest qualification, revocation propagation, discovery graph, privacy-bounded measurement, settlement recalculation, partner adapter allowlist, WORM/legal-hold export, and 12-month drills.

It is **not** production WORM, KMS, identity, gateway, or SIEM. It is the map of what Three-Zone must never contradict.

### The blockchain, named clearly

The blockchain in this system is the **XRP Ledger (XRPL)**.

Three-Zone does **not** put video on a chain. It does **not** put passwords, leases, or family identity on a chain. It writes a **canonical audit event** first (hash-chained, append-only, in SQLite). Then a publisher may submit a **hash manifest** of that audit event to XRPL so a third party can later prove "this operational record existed and has not been rewritten."

In demo/local, XRPL publication is **simulated**: a fake transaction id `DEMO-` plus a hex prefix, status `VALIDATED`, flag `simulated=1`. The test `test_audit_persists_before_simulated_xrpl_receipt` locks the order: **audit first, chain receipt second**.

In `TZ_ENV=production`, the process **refuses to start** unless XRPL settings are complete: RPC URL, network, audit account, signing secret, and key id. The live XRPL submit client is **not yet implemented**; the tables, hashes, config gate, and simulated publisher are in place so the contract is visible.

---

## Protection doctrine

Four non-negotiable rules. Everything else is an implementation detail.

### Player is never the authority

The browser video tag cannot decide if you may watch. Neither can a WebSocket message.

Authorization happens twice:

1. **Issue time.** `request_playback` (member path or ops path) evaluates the live event and rights. On success it issues a short HMAC **lease**. The lease token is delivered as an HTTP-only cookie scoped to that media path. The media URL itself has **no bearer token**.
2. **Serve time.** Every request to `/demo/media/{event_id}.mp4` (and `/api/leases/validate` for a future CDN) re-runs `validate_lease`. If rights were revoked, re-versioned, the window closed, the account died, or the token was tampered, the answer is 403.

A socket `rights.revoked` message only makes the UI stop faster. It is not enforcement.

### AI is never the authority

- Product code talks to `threezone_ai.gateway.run` / lineage / `cut_clip` only — never `threezone_ai.providers.*`.
- Process kill switch `THREEZONE_AI_ENABLED` must be explicitly true. Unset, blank, false-like, or malformed → disabled.
- Config/YAML `enabled` can further restrict; it cannot enable alone.
- Lineage records generation, human edit, and approval locally. Approval is **not** Moten R1/R2/signer and is **not** a rights decision.
- V0 vision models emit **observations**. `SportsContextPolicy` emits the only decision in that library. Publication / rights / settlement are out of scope for V0.
- L1B private live does **not** call AI.

### Truth is versioned and append-only

Rights are never silently edited for a restore — a new version is inserted. Operational `audit` and canonical `audit_events` are append-only. XRPL receives hashes of records that already exist. Client-supplied "truth fields" on L1B create payloads are stripped server-side.

### Moten is evidence handoff, not a second control plane

Three-Zone keeps running if Moten is unavailable. Jobs queue in `moten_outbox`. Delivery posts to Moten's `/intake/{handoff_type}` with a shared secret. A Moten response body with `accepted: true` means Moten **received** the packet. It does **not** mean three humans reviewed AI output, and it does not move Three-Zone lifecycle, rights, or leases.

---

## Roles

| Side | Role in the database | Demo account | Password (local/demo only) | Where you land |
| --- | --- | --- | --- | --- |
| Member site | `viewer` | `demo-viewer` | `change-me-viewer-local` | `/` |
| Back worker | `operator` | `demo-worker` | `change-me-worker-local` | `/ops` |
| Owner back portal | `owner` | `demo-owner` | `change-me-owner-local` | `/ops` |

Role `admin` is treated like owner for inventory/mastery gates in several paths. Override passwords with `TZ_SEED_PASSWORD_VIEWER`, `TZ_SEED_PASSWORD_WORKER`, `TZ_SEED_PASSWORD_OWNER`. Production refuses the demo values.

**Members** see only entitled zones and packages. They watch live and replay, use the member network (posts, games, clips, friends, watch parties). They cannot create control-plane events, revoke rights, import schedules, open L1B sessions, or open inventory.

**Workers (operators)** run production: create events, move lifecycle, scoreboard, ingest tokens, cameras, revoke/restore rights, schedules, analytics, audit, Moten handoffs, network review, L1B when flagged on. They cannot open the owner inventory or Mastery API.

**Owners** can do everything a worker can, plus print/export the whole site, print this mastery guide, issue staff accounts, and export network evidence packs.

Staff cannot self-register. `POST /api/auth/register` always creates a **viewer** with midwest / standard / web. Usernames `demo-owner`, `demo-worker`, `demo-admin`, `owner`, `operator`, `admin`, `root`, `system` are reserved. An owner issues worker or owner accounts with `POST /api/owner/staff`.

A signed-in worker or owner on `/` sees a **Control plane** link. `/ops` has a **Member site** link.

---

## Startup

`python run.py` does this:

1. Read configuration from the environment (`Config.from_env`).
2. Open SQLite at `TZ_DATABASE_PATH` (default `data/three_zone.sqlite3`), or Postgres when `TZ_DATABASE_URL` is set.
3. Create every table if missing. Migrate additive columns on old databases.
4. Seed demo users always (upsert). Seed demo events only if the events table is empty.
5. Start a **separate WebSocket process** (`multiprocessing`, daemon) sharing the same SQLite file in WAL mode — **except on Render**, where a second listen is disabled so `/healthz` on `$PORT` can succeed.
6. Serve HTTP in the parent process (`ThreadingHTTPServer`).
7. On Ctrl-C, shut down HTTP, terminate the WS process, close the database.

Default bind: HTTP `http://127.0.0.1:8000`, WebSocket `ws://127.0.0.1:8765/ws/events/<event_id>`.

Python packages: `websockets` plus optional AI/provider extras as needed. FFmpeg is optional (demo MP4 and studio clip cut).

Docker image runs `TZ_ENV=production` and therefore **refuses demo secrets**. You must pass real `TZ_TOKEN_SECRET`, `TZ_MEDIA_SERVICE_KEY`, `TZ_ALLOWED_ORIGINS`, seed passwords, and complete XRPL config. AI and private-live flags remain OFF unless you deliberately enable them.
---

## Auth, sessions, and cookies

There are **two session systems** on purpose.

### Control-plane session (Bearer token)

Used by `/ops` and most `/api/*` routes.

- Format: HMAC token type `session`, claim `sub` = `user_id`, TTL `TZ_SESSION_TTL` (default 3600 seconds).
- Stored in `sessionStorage` as `tz_session`.
- Sent as `Authorization: Bearer <token>`.
- Created by password login, register, or demo-login.

### Member session (HTTP-only cookie)

Used by member APIs (`/api/member/*`) and many network routes.

- Cookie name: `tz_member_session`
- Path `/`, `HttpOnly`, `SameSite=Strict`, Max-Age = session TTL
- Value is a `SES-…` id in table `member_sessions`
- Bound to a Treasure `verification_id`
- Created by `PortalService.complete_auth` after login/register/verify

Password login and register call `complete_auth`, so **both** the Bearer token and the member cookie are issued.

Logout: `POST /api/auth/logout` revokes the member session row and clears the cookie. The ops UI also drops `tz_session` from `sessionStorage`.

### Password engine

File: `backend/passwords.py`.

- Hash: `pbkdf2$sha256$210000$<salt hex>$<digest hex>`
- 16 random bytes of salt, 210,000 iterations, SHA-256, constant-time compare
- Username: lowercase, regex `^[a-z0-9][a-z0-9_-]{2,31}$`
- Password: 8 to 128 characters
- Wrong password and unknown user both return the same 401 `invalid_credentials`
- Suspended accounts (`account_state != active`) return 403 `account_suspended`

### Demo login (tests and old clients)

`POST /api/auth/demo-login` with `{ "account": "demo-viewer" | "demo-worker" | "demo-owner" }` still works. The member UI no longer uses it as the primary path.

### Treasure-backed verify (older member path)

`POST /api/auth/start` then `POST /api/auth/verify` still exist. Start maps unknown identifiers to `demo-viewer` except `andre`. Verify runs Treasure simulation and sets the member cookie. This is the anonymous-to-authorized path for the older "Verify and enter" flow.

### Route auth classes (HTTP router)

| Auth label | Meaning |
| --- | --- |
| `none` | Public (may still check service keys or ingest tokens inside the handler) |
| `optional` | Member cookie if present; anonymous otherwise |
| `member` | Valid member session cookie + live Treasure verification |
| `session` | Valid Bearer session token (any role) |
| `operator` | Bearer session with role operator/owner/admin |
| `owner` | Bearer session with role owner/admin |

---

## Event lifecycle

An **event** is one game (or other show) the control plane owns.

Lifecycle, in order, no skipping:

`scheduled → gray → yellow → green → live → replay → archive`

Allowed next states are hard-coded in `control_plane._ALLOWED_TRANSITIONS`. Jumping `scheduled` to `live` is `illegal_transition` (409).

**Guards:**

- To enter **yellow**, a rights object must exist.
- To enter **green** or **live**, active (non-revoked) rights must exist **and** a **fresh production heartbeat** must exist on the effective source (primary or backup). That is `production_not_ready` if the encoder has not checked in within `TZ_HEARTBEAT_TIMEOUT` seconds (default 12).
- **live → replay** can be done by an operator transition, or automatically by the media service calling `POST /api/events/{id}/media/end` with header `X-Media-Service-Key`. Only a live event can end this way (`not_live`). Replay sets `replay_available=1`.
- **archive** is terminal.

**Gray gate (open):** `gray` is a real lifecycle state between scheduled and yellow. Automated clearance that would consume a Treasure AI packet (or Moten review result) to advance gray is **not implemented as an owned contract**. Humans still walk the transitions. Do not claim AI or Moten clears gray.

Production modes stored on the event: `single_camera`, `multi_camera`, `backup_active`.

Zones: `midwest`, `west`, `east`. Create-event rejects any other zone (`bad_zone`).

Scoreboard is a JSON object on the event: typically `home`, `away`, `period`, `clock`. Updating it writes audit `event.score`, socket `score.update`, and may ingest a detected moment for the member timeline.

Camera attach (`POST /api/events/{id}/camera/attach`) binds a registered RTSP/ONVIF source for station workflows without replacing the rights/lease loop.

---

## Rights

Rights are **versioned**. They are never silently edited in place for a restore.

Each rights row includes: event_id, version, territory, destination, package, live_start, live_end, replay_start, replay_end, authority, source_reference, active, revoked, revocation_reason, archive_retention_days (default 365), created_at. Unique on `(event_id, version)`.

**Current rights** = highest version that is `active=1` and `revoked=0`.

**Revoke:** mark that row `active=0`, `revoked=1`, store a reason. Socket `rights.revoked`. Existing leases fail on next media check (`rights_unavailable` or, after restore, `rights_version_changed`).

**Restore:** insert a **new** version copied from the latest historical row. Old revoked rows remain forever. Owner inventory prints every version.

Creating an event always inserts rights version 1: territory = zone, destination default `web`, package default `standard`, live window start→+3 hours, replay window start→+30 days, authority = operator display name, source_reference `contract://{event_id}`.

Seeded events use authority **State Athletic Association**.

---

## Entitlement (policy decision point)

`ControlPlane.evaluate_access(user, event_row, mode=None)` is pure. It does not issue tokens. It returns allow/deny plus a public subset that does not leak extra reasons.

Checks, in order:

1. `account_state` must be `active` else `account_suspended`
2. `subscription` must be `active` else `subscription_inactive`
3. User zones must include the event zone, or `*` else `zone_not_entitled`
4. Active rights must exist else `rights_unavailable`
5. User packages must include the rights package, or `*` else `package_not_entitled`
6. User destinations must include the rights destination, or `*` else `destination_not_allowed`
7. Event status must be `live`, `replay`, or `archive` else `not_playable` (green/yellow/gray/scheduled are not playable)
8. Optional `mode` must match the resolved mode else `mode_mismatch`
9. Current time must fall inside the live window (for live) or replay window (for replay/archive) else `window_not_open` / `window_closed`

demo-viewer: zones `[midwest]`, packages `[standard]`, destinations `[web]`. West/East events are denied.

demo-worker and demo-owner: zones/packages/destinations `["*"]`.

---

## Leases

On allow, `request_playback` signs a token type `lease` with claims:

- `sub` — user_id
- `event_id`
- `rights_version`
- `mode` — live | replay | archive
- `lease_id` — random hex
- `typ`, `iat`, `exp`

TTL: `TZ_PLAYBACK_LEASE_SECONDS` / `TZ_LEASE_TTL` (default **60 seconds**, hard-capped at 60). Short on purpose.

HTTP handler **strips `lease_token` from JSON** and sets cookie:

`tz_lease_{event_id}=<token>; Path=/demo/media/{event_id}.mp4; Max-Age=<lease_ttl>; HttpOnly; SameSite=Strict`

JSON still returns `allow`, `mode`, `rights_version`, `lease_id`, `lease_ttl`, `media_url`.

`validate_lease` checks signature, type, expiry, event match, subject exists, event exists, `evaluate_access` with the bound mode, and **exact rights_version match**.

Member playback also inserts `lease_records` and writes canonical audit `lease.issued` (and `playback.requested` / `lease.denied`).

---

## Media

### Demo rail (default)

File: `backend/demo_media.py`. Default `TZ_LIVE_MEDIA_PROVIDER=demo` (legacy alias `TZ_MEDIA_PROVIDER`).

This is **not** production video. It generates a small local MP4 (FFmpeg testsrc color bars if FFmpeg exists, otherwise a tiny structurally valid MP4 that may not render). Path: `{data_dir}/media/{event_id}.mp4`.

`GET /demo/media/{event_id}.mp4`:

1. Read cookie `tz_lease_{event_id}`
2. If missing → 403 `no_lease`
3. `validate_lease` → 403 on failure
4. Honor HTTP `Range` (206 partial, 416 unsatisfiable)
5. `Cache-Control: no-store`

### Hosted rail (Cloudflare)

When `TZ_LIVE_MEDIA_PROVIDER=cloudflare` and credentials are complete, operators can provision live inputs, rotate keys, sync status, and receive webhooks at `POST /api/media/webhooks/cloudflare`. A signed HLS URL is not an instant kill switch — lease validation remains the authority for the demo path and for `POST /api/leases/validate` with `X-Media-Service-Key`.

Mux is a later empty seam on the same `MediaProvider` interface.

### UGC / network media

Member network uploads use `TZ_UGC_MEDIA_PROVIDER` (`fake` default, or `cloudflare`). Photos never go to Stream (`TZ_PHOTO_STORAGE=fake|s3`). Fake upload and webhook routes exist for CI.

`POST /api/events/{id}/media/end` uses the media service key to flip live → replay.

---

## Ingest, heartbeat, and failover

Operators issue an **ingest token** (type `ingest`) scoped to one `event_id` and one `source` (`primary` or `backup`), plus a unique `jti`. TTL `TZ_INGEST_TTL` (default 6 hours).

The encoder (example script `scripts/ingest_heartbeat.py`) POSTs:

`/api/events/{id}/ingest/heartbeat` with `{ ingest_token, source, healthy }`

The token must match event **and** source (`ingest_scope`).

If `healthy` is true, `primary_last_seen` or `backup_last_seen` is stamped now. If false, last-seen is not updated (it goes stale).

**Effective source:** prefer a fresh primary; else a fresh backup; else keep the stored `active_source`. Fresh means last-seen within `heartbeat_timeout`.

When effective source changes, audit `feed.failover` and socket `feed.heartbeat`.

The WebSocket process also runs a **feed_loop** every 2 seconds on green/live events to detect timeout failover even if no new heartbeat arrives.

Without a fresh heartbeat, the event cannot go green or live.

Live-readiness report: `GET /api/ops/live-readiness` (operator) summarizes whether production can go live under current flags and credentials.

---

## Sockets

Separate process (when not on Render). Path: `ws://{host}:{ws_port}/ws/events/{event_id}`

**Admission:**

- `Origin` must be in `TZ_ALLOWED_ORIGINS` or the handshake is closed 1008
- Path must start `/ws/events/`
- Session token must be offered in `Sec-WebSocket-Protocol` as a value **other than** the dummy `tz-session` (the browser sends `["tz-session", token]`)
- Token must verify as type `session`
- Event must exist
- User must be zone-entitled
- Per-IP connection cap default 20 (`ws_max_conns_per_ip`)
- Max message size 16 KiB
- Per-connection 40 messages / 10 seconds
- Ping/pong every 20s, timeout 20s
- SIGINT/SIGTERM clean shutdown

**On connect:** send `event.state` with a full event snapshot.

**Client messages:** `ping` → `pong`; `renew` → re-run `evaluate_access` and send `lease.status`.

**Fan-out:** HTTP writes `socket_outbox`. WS process polls every 0.3s, broadcasts, marks `delivered=1`.

**Metrics:** every 3s write `socket_metrics` (single row id=1): total connections, per-event counts, updated_at. Analytics treats metrics as fresh if updated within 10 seconds.

Socket types: `event.state`, `score.update`, `feed.heartbeat`, `rights.revoked`, `rights.restored`, `lease.status`, `pong`.
---

## Member site, network, Huddle, and Studio

### Sports Access (member catalog)

Pages: `/` (`index.html` + `portal.js` + `styles.css`).

After sign-in: Live, Schedules, Archives, search, Watch, plus network surfaces. No marketing hero.

**Live** — events in status live, green, or scheduled that the member is zone-entitled to see. Green/scheduled cards still say Watch; playback will fail with a toast if not actually playable.

**Schedules** — versioned fixtures: school, team, opponent, date, location, home/away, season.

**Archives** — `archive_objects` with status ARCHIVED, joined to school and team.

**Search** — schools, teams, and entitled event titles. Minimum 2 characters in the UI.

**Watch** — `POST /api/member/events/{id}/playback` then `<video src="{media_url}?lease={lease_id}">`. The query string is **not** the secret; the cookie is.

**Moments / timeline** — `GET /api/member/events/{id}/moments` and `/timeline` expose detected moments derived from score/signals (candidates, not AI vision HTTP).

Catalog seed (`_ensure_catalog`) uses `INSERT OR IGNORE` so concurrent tabs cannot UNIQUE-crash.

Seeded catalog:

- Schools: Lincoln High, Lakeside Prep, Northridge (all midwest)
- Teams: Lincoln Freshman Basketball (freshman basketball), Lakeside Prep Basketball, Northridge Soccer
- Schedule `sch-lincoln-2026` version 1: vs Central Valley (home, Riverside Stadium), vs Maple Grove (away, Lakeside Gym)
- Archive `arc-central-wrestling` → event `evt_mw_wrestling`, title "Central Wrestling — Full Game"

Schedule CSV import (operator) required columns: school, team, sport, level, opponent, date, start time, location, home/away, season. Bad rows rejected; a good file creates a **new version** and keeps the old. Unknown school/team rejected. Duplicate opponent+start rejected.

Public (no cookie) mirrors exist for marketing/SEO cards: `GET /api/public/live`, `/api/public/schedules`, `/api/public/archives` — still filtered to non-sensitive catalog facts.

### Member network

Profiles, follows, posts, games, clips, reactions, comments, saves, shares/inbox, reports, moderation cases, notifications. Media upload jobs with fake or Cloudflare providers. Operator review queues for games and cases. Owner evidence export for game/clip/post.

Static sharable pages: `/moment/…`, `/post/…`.

### Huddle (friends + watch parties)

Friend request / accept / unfriend / block. Friends activity feed. Watch parties with join codes and messages. Settings include `show_watching_to_friends`.

### Studio sources

`GET /api/member/studio/sources` lists sources a member may clip from (rights-aware). AI clip cut (`POST /api/ai/clips/cut`) is a separate gated path under the AI flag.

---

## Operator console

Dark operational console at `/ops`. Left sidebar. One pane at a time.

**Catalog** — all events the caller may see (workers/owners: all zones). Filter chips: all, midwest, west, east. Cards show status, zone, category, score, feed pill, Open / Watch replay.

**Player** — lease-gated video, score, feed health, socket log. Select an event from Catalog first.

**Operations**

- Create event — title, zone, category, production mode
- Event controls — next lifecycle button only, revoke/restore, scoreboard, ingest token issue, camera attach, media provision/sync when hosted
- Schedule import — CSV preview; malformed rows rejected; new version on correction
- Cameras — register RTSP/ONVIF sources
- L1B live sessions — when flag on: create / get / stop private capture
- Moten — discovery + intake handoffs
- Analytics and audit — JSON analytics + scrolling audit list
- Ops dashboard — `GET /api/ops/dashboard` aggregates readiness, Moten outbox, live sessions

**Owner dropdown** (hidden unless role is owner/admin)

- Inventory — load / print everything / download JSON
- Mastery — this document, print in plain English

**Account** — who you are, Member site, Sign out.

Viewers who log in on `/ops` are redirected to `/`.

---

## Owner portal

`GET /api/owner/inventory` requires role owner or admin.

Payload includes: `generated_at`, public `environment`, `tiers`, `routes`, `totals`, `users` (no password_hash), `events` with **all** rights versions, operational `audit`, `analytics`, and network inventory counts when available.

UI: Load full inventory fills a white print document (`#print-root`). Print everything uses `window.print()` with CSS that hides the dark chrome. Download JSON saves `three-zone-inventory-{timestamp}.json`.

`GET /api/owner/mastery` returns `{title, html}` of this guide.

`POST /api/owner/staff` issues operator or owner accounts.

Workers hitting owner APIs get 403 `owner_required`.

Network evidence: `GET /api/network/evidence/{game|clip|post}/{id}` (+ `.csv` / `.html`).

---

## AI sovereignty (gateway, lineage, V0 vision)

### What exists

Package `threezone_ai/` is the **only** product-facing AI surface. Entry points exported from `threezone_ai`:

- `run(AIRequest)` — sovereignty switchboard
- `select_providers`
- `record_generation` / `record_human_edit` / `record_approval` / `get_lineage`
- `cut_clip` / `ffmpeg_available` (studio helper; not a model)

Task types: `caption`, `embedding`, `moderation`, `description`.

Providers (behind the gateway only): Ollama chat/embed, local whisper, local moderation, Groq chat/whisper, Gemini chat, Cloudflare Workers AI chat. Product code must not import providers.

### Process kill switch (Y1b)

`threezone_ai.config.process_ai_enabled()` reads `THREEZONE_AI_ENABLED` fail-closed (`1`/`true`/`yes`/`on` only).

`gateway.run`:

1. If process gate is OFF → immediate `AIResponse.no_ai` with error mentioning the process gate. No settings load, no credentials, no providers.
2. If Settings/config `enabled` is OFF → `no_ai` (config cannot enable alone).
3. Else select providers by task order, privacy block list, and cost ceiling; record lineage when appropriate.

HTTP flag mirror: `backend.ai_gateway_routes.ai_enabled()` uses the same env var. Mutating routes call `_require_ai()` and return **503** `{error: "ai_disabled", code: "ai_disabled"}` when off.

`GET /api/ai/status` is public and always returns `{enabled: bool, gateway: …|null}` without requiring the flag. When enabled, gateway summary includes task orders, privacy rules, cost tiers, lineage backend path presence, and which API keys are **present** (never the secrets).

### Product HTTP AI routes (exist; gated)

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/api/ai/status` | none | Always 200; reports enablement |
| POST | `/api/ai/transcribe` | member | Caption via `run` |
| POST | `/api/ai/search` | member | Embedding (+ optional in-request cosine hits) |
| POST | `/api/ai/complete` | member | Description via `run` |
| POST | `/api/ai/clips/cut` | member | FFmpeg cut under `media_dir`; optional title via Description |
| POST | `/api/ai/lineage/edit` | member | Local human_edit lineage record |
| POST | `/api/ai/lineage/approve` | member | Local approval lineage record |

**Lineage approve is local/member-gated.** It writes an append-only provenance event (`event=approval`) to `THREEZONE_AI_LINEAGE_PATH` (default `data/lineage.jsonl`, backend `jsonl` or `sqlite`). It is **not** Moten R1/R2, not a Moten signer, not a rights restore, and not gray-gate clearance.

### Config / keys (optional until enabled)

See `config.example.env`: `THREEZONE_AI_CONFIG`, `THREEZONE_AI_LINEAGE_PATH`, `THREEZONE_AI_LINEAGE_BACKEND`, `OLLAMA_*`, `LOCAL_WHISPER_MODEL`, `THREEZONE_AI_HTTP_TIMEOUT`, `THREEZONE_AI_OLLAMA_TIMEOUT`, optional `GROQ_*`, `GEMINI_*`, `CLOUDFLARE_*` for AI (separate from Stream live credentials).

### V0 sports vision (library-only)

Package `threezone_ai.vision`:

- **Not** imported by `backend.http_server`, `run.py`, or the AI gateway startup path.
- **No** product HTTP route, worker admission, or gateway task registration.
- Models emit observations; `evaluate_sports_context` / `SportsContextPolicy` emit the only decision.
- Fake providers only in CI until real weight licenses are recorded.
- Offline entry: `python -m threezone_ai.vision.offline_entry asset:synthetic:<id>` (must not be wired to HTTP).
- Versions: evidence schema `threezone.vision.evidence.v0`, ontology `threezone.vision.ontology.v0`, policy `sports-context-policy.v0`.

### Open AI / Treasure ownership

Gray-gate automation and **Treasure AI packet ownership** (who authors, stores, and signs an AI evidence packet that could influence clearance) remain **open**. Do not document a closed design that the code does not implement.

Production AI remains **OFF by default**.

---

## Private live capture (L1B)

Module: `backend/live_sessions.py`. Table: `live_sessions`. Flag: `THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED` (default false, fail-closed). Related future flags (also default false, not implemented in L1B): `THREEZONE_MEMBER_LIVE_ENABLED`, `THREEZONE_SPORTS_VERIFY_ENABLED`, `THREEZONE_LIVE_PUBLICATION_ENABLED`, `THREEZONE_LIVE_CONTINUOUS_VERIFY_ENABLED`.

### Who and what

- **Operator/owner only** (`require_operator` + flag).
- Creates a private capture session for local browser preview.
- Server-forced truth on create (clients cannot override; truth fields are stripped):
  - `public_state=LIVE_PRIVATE`
  - `distribution_state=DISABLED`
  - `sports_status=UNVERIFIED`
  - `safety_state=NOT_EVALUATED`
  - `provider_name=local_browser`
- Does **NOT** call media_provider, Restream, AI, XRPL, settlement, Moten intake, or `ControlPlane.transition(live)`.
- Audits via `ControlPlane.audit_log` only (no Moten outbox for these events).
- Publication label always: "Private capture session — Browser source not published".

### Lifecycle

```text
REQUESTED → CAPTURE_STARTING → VERIFYING_PRIVATE → STOP_REQUESTED → STOPPED
REQUESTED | CAPTURE_STARTING | VERIFYING_PRIVATE → FAILED
```

Create advances synchronously REQUESTED → CAPTURE_STARTING → VERIFYING_PRIVATE (no external provider provisioning). Stop walks STOP_REQUESTED → STOPPED. Idempotency keys are honored; reuse with different input fingerprints is `idempotency_conflict`.

### HTTP

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/api/live-sessions` | operator | Create; 503 if flag off |
| GET | `/api/live-sessions/{ls_…}` | operator | Read |
| POST | `/api/live-sessions/{ls_…}/stop` | operator | Stop |

Ids match `ls_[a-z0-9]+`. Policy version string: `l1b-private-v1`.

Private-live flags remain **OFF by default** in production.

---

## Treasure

Treasure is the **identity/evidence verifier**, not the video CDN.

`PortalService.verify_treasure(member_id)`:

- If env is not `demo`, `development`, or `local` → `verification_unavailable` (fail closed)
- Else insert `member_verifications`: status `VERIFIED`, type `member_access`, 1 hour expiry, evidence hash of `{member_id, type, at}`, verifier `treasure-network`, receipt id `TRR-…`, `simulated=1`
- Canonical audit `treasure.verification.completed`

A member session is valid only if that verification is still VERIFIED and unexpired. Revoking the verification row denies playback (`verification_required`).

Internal operator routes (Bearer operator):

- `POST /internal/treasure/verify`
- `POST /internal/treasure/revalidate`

Both currently call the same verify helper.

This is TR-06 in miniature: you do not get a member cookie until verification exists.

**Open:** Treasure AI packet ownership for sports-context / gray-gate evidence is not closed.

---

## Moten handoffs

Module: `backend/moten_adapter.py` (`MotenIntakeService`).

Enablement: `config.moten_enabled` when `TZ_MOTEN_SERVICE_URL` is set (shared secret `TZ_MOTEN_SHARED_SECRET`, timeout `TZ_MOTEN_TIMEOUT_SECONDS` default 5).

### Behavior

1. Operator (or runtime helper) builds a typed payload (`three-zone.moten.{type}.v1`).
2. Row inserted into `moten_outbox` with status `queued` (or `skipped` if Moten not configured).
3. Background thread POSTs to `{MOTEN_URL}/intake/{handoff_type}` with headers `Content-Type: application/json`, `X-Moten-Shared-Secret`, `X-Three-Zone-Source: three-zone-api`.
4. On HTTP success → status `delivered` (response body stored; Moten test harness returns `{"accepted": true, …}`).
5. On HTTP/network failure → status `failed` with error detail. Three-Zone continues.

**`accepted` means Moten receiver acceptance of the evidence packet. It does not mean three-human AI review, Moten R1/R2 approval, or any Three-Zone lifecycle change.**

### Handoff types

| Type | Source | Payload highlights |
| --- | --- | --- |
| `event` | operator | event snapshot + current rights + recent audit |
| `rights-version` | operator | rights row (+ optional version pin) |
| `revocation-event` | operator | latest revoke/restore audit + rights history |
| `settlement` | operator | settlement manifest |
| runtime types | member runtime via `enqueue_runtime` | schema auto-filled |

### HTTP

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/api/moten/discovery` | operator |
| GET | `/api/moten/intake/jobs/{mtn_…}` | operator |
| POST | `/api/moten/intake/event` | operator |
| POST | `/api/moten/intake/rights-version` | operator |
| POST | `/api/moten/intake/revocation-event` | operator |
| POST | `/api/moten/intake/settlement` | operator |

Outbox statuses you will see: `queued`, `skipped`, `delivered`, `failed`.

L1B does **not** enqueue Moten jobs.

---

## Audit and XRPL

There are **two audit ledgers**, plus settlement publication queue tables.

### Operational audit (`audit` table)

Simple append-only log the operator UI reads (`GET /api/audit`): id, ts, actor, action, event_id, detail JSON.

Actions include: `auth.login`, `auth.register`, `auth.staff_issued`, `auth.demo_login`, `event.created`, `event.transition`, `event.score`, `event.media_end`, `rights.revoked`, `rights.restored`, `ingest.token_issued`, `feed.failover`, `playback.granted`, `playback.denied`, `seed.loaded`, `live_session.*`, plus portal event types copied through `audit_log`.

Also: `GET /api/audit/verification-outbox` for Treasure/audit delivery outbox rows.

### Canonical hash-chained audit (`audit_events` table)

This is the legal-grade stream.

Each row:

- `event_id` like `AUD-…` (not a sports event id)
- `event_type`, `entity` (`three-zone`), `source_service` (`three-zone-api`)
- `subject_id`, `actor_type`, `actor_id`
- `occurred_at`, `recorded_at`
- `payload_version` `1.0`
- `payload` JSON, `payload_hash` = `sha256:` + SHA-256 of canonical JSON
- `previous_event_hash` — hash of the previous payload, forming a **hash chain**
- `correlation_id`, `verification_ref`, `rights_version`
- `legal_effect` currently `operational_record`

Portal event types written here include: `treasure.verification.completed`, `member.login.requested`, `member.login.denied`, `member.login.success`, `event.discovered`, `playback.requested`, `lease.denied`, `lease.issued`, `schedule.version.created`.

### XRPL publications (`xrpl_publications` table)

`publish_pending()` selects canonical audit events with **no** XRPL row yet, oldest first. For each:

- Build `manifest_hash` = sha256 of `{audit_event_id, payload_hash}`
- In demo: `xrpl_transaction_hash` = `DEMO-` + first 24 hex of sha256(manifest)
- `xrpl_account` = `demo-audit-account`
- `ledger_index` = `simulated-ledger`
- `status` = `VALIDATED`
- `simulated` = 1

What is **not** on the ledger: video, cookies, passwords, display names, raw payloads. Only hashes.

Operator inspection: `GET /api/admin/audit/{AUD-…}` and `…/xrpl`.

Publisher trigger: `POST /internal/audit/events` (operator) returns `{ publication_ids, simulated: true }`.

Settlement side also has `settlements`, `settlement_leaves`, `xrpl_publication_queue`, `view_sessions`, `viewing_heartbeats`, `provider_analytics_snapshots` for measurement manifests and Merkle proofs (property APIs under `/api/properties/…/settlements`).

**Honest status:** the hash chain and simulated publisher are real code. A live signed XRPL submit over RPC is the next construction step. Do not claim mainnet settlement from this MVP.
---

## Full API catalog

Inventory from `backend/http_server._routes()` plus `ai_gateway_routes.extra_routes()`, plus static/special handlers. Event ids in paths match `evt_[a-z0-9_]+`. Bodies larger than 64 KiB → 413 `body_too_large` (webhooks allow a larger cap). Bad JSON → 400 `bad_json`. Unknown path → 404 `not_found`. Disallowed Origin → 403 `forbidden_origin`. Missing Bearer where required → `missing_session`. Uncaught exception → 500 `internal` with no traceback in the body.

### Static and special pages

| Method | Path | Who | What |
| --- | --- | --- | --- |
| GET | `/` | public | Member site |
| GET | `/ops` `/ops.html` `/ops/` | public | Control plane console |
| GET | `/three-zone-mastery` `/THREE_ZONE_MASTERY.md` | public | Printable mastery |
| GET | `/moment/…` | public | Moment share page |
| GET | `/post/…` | public | Post share page |
| GET | `/vendor/…` | public | Vendored static (no `..`) |
| GET | `/favicon.ico` | public | Empty 204 |
| GET | `/demo/media/{evt_…}.mp4` | lease cookie | Bytes after re-check |
| WS | `/ws/events/{evt_…}` | session subprotocol | Live state fan-out |

### Public / none

| Method | Path | What |
| --- | --- | --- |
| GET | `/api/health` `/healthz` `/health` | Liveness `{status: ok}` |
| GET | `/api/config` | Ports, TTLs, zones; never secrets |
| GET | `/api/public/live` | Public live cards |
| GET | `/api/public/schedules` | Public schedules |
| GET | `/api/public/archives` | Public archives |
| POST | `/api/auth/demo-login` | Demo account picker |
| POST | `/api/auth/login` | Password login |
| POST | `/api/auth/register` | Create viewer only |
| POST | `/api/auth/start` | Treasure verify start |
| POST | `/api/auth/verify` | Treasure verify finish |
| POST | `/api/auth/logout` | Clear member session |
| GET | `/api/ai/status` | AI enablement summary |
| POST | `/api/leases/validate` | CDN re-check (`X-Media-Service-Key`) |
| POST | `/api/media/webhooks/cloudflare` | Live rail webhooks |
| POST | `/api/network/webhooks/media` | UGC media webhooks |
| POST | `/api/network/provider/fake/upload/{token}` | CI fake upload |
| POST | `/api/events/{evt}/view-sessions` | Start view session |
| POST | `/api/view-sessions/{VS-…}/heartbeat` | Viewer heartbeat |
| POST | `/api/view-sessions/{VS-…}/end` | End view session |
| POST | `/api/events/{evt}/ingest/heartbeat` | Encoder heartbeat (ingest token) |
| POST | `/api/events/{evt}/media/end` | live→replay (media service key) |

### Optional (member cookie if present)

| Method | Path | What |
| --- | --- | --- |
| GET | `/api/member/feed` | Member/network feed |
| GET | `/api/network/feed` | Network feed |
| GET | `/api/network/profiles/{handle}` | Profile |
| GET | `/api/network/profiles/{handle}/{posts\|clips\|games\|saved}` | Profile tab |
| GET | `/api/network/posts/{pst_…}` | Post get |
| GET | `/api/network/games/{gme_…}` | Game get |
| GET | `/api/network/clips/{clp_…}` | Clip get |
| GET | `/api/network/comments` | List comments |
| GET | `/api/network/media/{med_…}` | Media asset |

### Member cookie required

| Method | Path | What |
| --- | --- | --- |
| GET | `/api/member/me` | Member identity + verification |
| GET | `/api/member/live` | Entitled live/upcoming |
| GET | `/api/member/schedules` | Schedules |
| GET | `/api/member/archives` | Archives |
| GET | `/api/member/search` | Discovery `?q=` |
| POST | `/api/member/events/{evt}/playback` | Lease + media cookie |
| POST | `/api/member/archive/{id}/playback` | Archive lease |
| GET | `/api/member/events/{evt}/moments` | Detected moments |
| GET | `/api/member/events/{evt}/timeline` | Timeline |
| GET | `/api/member/notifications` | Notifications |
| POST | `/api/member/notifications/{ntf}/read` | Mark read |
| GET | `/api/member/settings` | Settings |
| POST | `/api/member/settings` | Update settings |
| GET | `/api/member/friends/activity` | Friends activity |
| POST | `/api/member/friends/{handle}/request` | Friend request |
| POST | `/api/member/friends/{handle}/accept` | Accept |
| POST | `/api/member/friends/{handle}/unfriend` | Unfriend |
| POST | `/api/member/blocks/{handle}` | Block |
| POST | `/api/member/blocks/{handle}/delete` | Unblock |
| POST | `/api/member/follows/teams/{team}` | Follow team |
| POST | `/api/member/follows/teams/{team}/delete` | Unfollow team |
| GET | `/api/member/studio/sources` | Studio sources |
| POST | `/api/member/watch-parties` | Create party |
| GET | `/api/member/watch-parties/{party}` | Get party |
| POST | `/api/member/watch-parties/{party}/join` | Join |
| POST | `/api/member/watch-parties/{party}/messages` | Message |
| POST | `/api/member/posts/{pst}/share` | Share post |
| POST/PUT | `/api/member/posts/{pst}/like` | Like |
| POST/DELETE | `/api/member/posts/{pst}/unlike` or `/like` | Unlike |
| GET | `/api/member/saved` | Saved items |
| POST | `/api/ai/transcribe` | AI caption (flag) |
| POST | `/api/ai/search` | AI embed/search (flag) |
| POST | `/api/ai/complete` | AI description (flag) |
| POST | `/api/ai/clips/cut` | Studio cut + optional title (flag) |
| POST | `/api/ai/lineage/edit` | Local lineage edit (flag) |
| POST | `/api/ai/lineage/approve` | Local lineage approve (flag) |
| GET/POST | `/api/network/me/profile` | Profile get/update |
| POST | `/api/network/profiles/{handle}/follow` | Follow |
| POST | `/api/network/profiles/{handle}/unfollow` | Unfollow |
| POST | `/api/network/uploads` | Start upload job |
| GET | `/api/network/uploads/{upl}` | Upload status |
| POST | `/api/network/uploads/{upl}/cancel` | Cancel |
| POST | `/api/network/uploads/{upl}/retry` | Retry |
| POST | `/api/network/posts` | Create post |
| POST | `/api/network/posts/{pst}` | Update post |
| POST | `/api/network/posts/{pst}/delete` | Delete post |
| POST | `/api/network/games` | Create game |
| POST | `/api/network/games/{gme}/attach` | Attach media |
| POST | `/api/network/games/{gme}/playback` | Game playback |
| POST | `/api/network/clips` | Create clip |
| POST | `/api/network/clips/{clp}/render` | Render |
| POST | `/api/network/clips/{clp}/publish` | Publish |
| POST | `/api/network/react` | React |
| POST | `/api/network/unreact` | Unreact |
| POST | `/api/network/comments` | Create comment |
| POST | `/api/network/comments/{cmt}/delete` | Delete comment |
| POST | `/api/network/saves` | Save |
| POST | `/api/network/saves/delete` | Unsave |
| POST | `/api/network/shares` | Share to inbox |
| GET | `/api/network/inbox` | Inbox |
| POST | `/api/network/inbox/{shr}/read` | Mark read |
| POST | `/api/network/reports` | Report content |

### Session Bearer (any role)

| Method | Path | What |
| --- | --- | --- |
| GET | `/api/me` | Control-plane identity |
| GET | `/api/events` | Catalog (zone filtered) |
| GET | `/api/events/{evt}` | Detail + public access decision |
| POST | `/api/events/{evt}/playback-session` | Ops/member lease |
| GET | `/api/analytics` | Counts + socket metrics |
| GET | `/api/properties/{pid}/settlements` | Settlements list |
| GET | `/api/properties/{pid}/settlements/{SET}` | Settlement detail |
| GET | `/api/properties/{pid}/settlements/{SET}/sessions` | Sessions |
| GET | `/api/properties/{pid}/settlements/{SET}/sessions/{VS}/proof` | Merkle proof |
| POST | `/api/properties/{pid}/settlements/{SET}/verify` | Verify manifest |

### Operator

| Method | Path | What |
| --- | --- | --- |
| GET | `/api/ops/live-readiness` | Live readiness report |
| GET | `/api/ops/dashboard` | Ops dashboard aggregate |
| POST | `/api/events` | Create event + rights v1 |
| POST | `/api/events/{evt}/transition` | `{target}` lifecycle |
| POST | `/api/events/{evt}/score` | Scoreboard |
| POST | `/api/events/{evt}/rights/revoke` | Revoke |
| POST | `/api/events/{evt}/rights/restore` | Restore → new version |
| POST | `/api/events/{evt}/ingest-token` | Issue ingest token |
| POST | `/api/events/{evt}/camera/attach` | Attach camera |
| POST | `/api/events/{evt}/media/provision` | Provision hosted input |
| POST | `/api/events/{evt}/media/rotate-key` | Rotate key |
| POST | `/api/events/{evt}/media/sync` | Sync provider state |
| GET | `/api/events/{evt}/media/status` | Media status |
| GET | `/api/events/{evt}/settlement-manifest` | Settlement manifest |
| GET | `/api/cameras` | List cameras |
| POST | `/api/cameras` | Register camera |
| POST | `/api/live-sessions` | L1B create (flag) |
| GET | `/api/live-sessions/{ls}` | L1B get |
| POST | `/api/live-sessions/{ls}/stop` | L1B stop |
| POST | `/api/admin/schedules/upload` | Schedule CSV |
| GET | `/api/audit` | Operational audit |
| GET | `/api/audit/verification-outbox` | Verification outbox |
| GET | `/api/admin/audit/{AUD}` | Canonical + XRPL |
| GET | `/api/admin/audit/{AUD}/xrpl` | Same handler |
| POST | `/internal/treasure/verify` | Treasure adapter |
| POST | `/internal/treasure/revalidate` | Same |
| POST | `/internal/audit/events` | Publish pending XRPL sims |
| GET | `/api/moten/discovery` | Moten status |
| GET | `/api/moten/intake/jobs/{mtn}` | Job status |
| POST | `/api/moten/intake/event` | Handoff event |
| POST | `/api/moten/intake/rights-version` | Handoff rights |
| POST | `/api/moten/intake/revocation-event` | Handoff revocation |
| POST | `/api/moten/intake/settlement` | Handoff settlement |
| GET | `/api/network/review` | Moderation queue |
| POST | `/api/network/review/games/{gme}` | Review game |
| POST | `/api/network/review/cases/{mod}` | Review case |
| POST | `/api/network/profiles/{prf}/verify` | Verify profile |

### Owner

| Method | Path | What |
| --- | --- | --- |
| GET | `/api/owner/inventory` | Full live dump |
| GET | `/api/owner/mastery` | `{title, html}` of this guide |
| POST | `/api/owner/staff` | Issue operator/owner |
| GET | `/api/network/evidence/{game\|clip\|post}/{id}` | Evidence JSON |
| GET | `/api/network/evidence/…/{id}.csv` | Evidence CSV |
| GET | `/api/network/evidence/…/{id}.html` | Evidence HTML |
---

## Database tables

SQLite (WAL, busy_timeout 5000 ms, foreign_keys ON) or Postgres via `TZ_DATABASE_URL`. Schema from `backend/db.py`. Complete inventory:

| Table | Purpose |
| --- | --- |
| `users` | Accounts: role, zones, packages, destinations, password_hash, properties |
| `events` | Sports/control events + lifecycle, feed last-seen, provider fields, scoreboard |
| `rights` | Versioned rights; UNIQUE(event_id, version) |
| `audit` | Operational append-only log |
| `audit_verification_outbox` | Delivery outbox for verification consumers |
| `moten_outbox` | Moten evidence handoff jobs |
| `socket_outbox` | WS fan-out queue |
| `socket_metrics` | Single-row connection metrics |
| `member_sessions` | HTTP-only member sessions bound to Treasure |
| `member_verifications` | Treasure VERIFIED records (simulated flag) |
| `schools` | School directory |
| `teams` | Teams under schools |
| `schedules` | Schedule heads (current_version) |
| `schedule_versions` | Immutable schedule versions |
| `schedule_events` | Rows inside a schedule version |
| `archive_objects` | Archived game cards |
| `camera_sources` | RTSP/ONVIF camera registry |
| `camera_secrets` | Secret refs for camera creds |
| `camera_archive_objects` | Camera archive objects + sha256 |
| `camera_archive_verification_outbox` | Camera archive verify outbox |
| `lease_records` | Member lease issuance records |
| `audit_events` | Hash-chained canonical audit |
| `xrpl_publications` | XRPL (often simulated) receipts for audit hashes |
| `view_sessions` | Authenticated viewing measurement sessions |
| `viewing_heartbeats` | Per-session heartbeat samples |
| `webhook_inbox` | Cloudflare/live webhook dedupe |
| `settlements` | Settlement manifests + merkle root |
| `settlement_leaves` | Per-session leaves + proofs |
| `xrpl_publication_queue` | Settlement publication queue |
| `provider_analytics_snapshots` | Provider vs TZ measurement variance |
| `profiles` | Member network profiles |
| `follows` | Profile follows |
| `media_assets` | UGC/media asset registry |
| `upload_jobs` | Upload job state machine |
| `provider_webhook_events` | UGC provider webhook dedupe |
| `posts` | Network posts |
| `games` | Member-uploaded games |
| `game_media` | Game↔asset links |
| `clips` | Derived clips |
| `reactions` | Likes/reactions |
| `comments` | Comments |
| `member_settings` | Privacy settings (e.g. show watching) |
| `team_follows` | Follow teams |
| `school_follows` | Follow schools |
| `friendships` | Friend graph |
| `member_blocks` | Blocks |
| `detected_moments` | Score/signal moments |
| `moment_signals` | Moment signal payloads |
| `watch_parties` | Watch parties |
| `watch_party_members` | Party membership |
| `watch_party_messages` | Party chat |
| `saves` | Saved subjects |
| `media_shares` | Direct shares / inbox |
| `athlete_tags` | Athlete tags on subjects |
| `team_tags` | Team tags on subjects |
| `notifications` | Notification inbox |
| `moderation_cases` | Moderation cases |
| `content_reports` | Member reports |
| `live_sessions` | L1B private live capture sessions |

JSON helpers: `dumps` (sorted keys, compact) and `loads`.

---

## Tokens

Format for session, lease, and ingest: `<base64url(json)>.<base64url(hmac_sha256)>`, no padding. HMAC-SHA256 with `TZ_TOKEN_SECRET`. Verify is constant time. Wrong `typ` is rejected. Expiry is unix seconds.

| typ | Bound to | Used for |
| --- | --- | --- |
| session | `sub` | HTTP Bearer and WebSocket subprotocol |
| lease | sub, event_id, rights_version, mode, lease_id | Media cookie |
| ingest | event_id, source, jti | Encoder heartbeat |

Media service key is **not** an HMAC token. It is a shared secret header `X-Media-Service-Key` (`TZ_MEDIA_SERVICE_KEY`), constant-time compared.

Passwords are PBKDF2, not HMAC tokens.

Moten shared secret is a header on outbound Moten intake only.

Upload tokens / Cloudflare signed URLs are provider-specific and short-lived; they are not Three-Zone HMAC types.

---

## Cookies

| Name | Path | Flags | Meaning |
| --- | --- | --- | --- |
| `tz_member_session` | `/` | HttpOnly, SameSite=Strict | Member portal session id |
| `tz_lease_{event_id}` | `/demo/media/{event_id}.mp4` | HttpOnly, SameSite=Strict | Playback lease for that file only |

No token is placed in URLs or server access logs. HTTP `log_message` is a no-op.

Browser `sessionStorage.tz_session` is the ops Bearer token (not a cookie).

---

## Denials and error codes

HTTP mapping: AuthError 401, ForbiddenError 403, NotFoundError 404, ConflictError 409, ValidationError/ControlError 400. Feature flags often 503.

| code | Meaning |
| --- | --- |
| invalid_credentials | Bad username or password |
| bad_username | Invalid or reserved register name |
| bad_password | Password not 8–128 chars |
| username_taken | Register conflict |
| unknown_account | Bad demo-login account |
| account_suspended | User not active |
| invalid_session | Bad/expired/unknown session |
| missing_session | No Bearer token |
| operator_required | Viewer tried a worker route |
| owner_required | Non-owner tried inventory/mastery API |
| event_not_found | Unknown evt_ id |
| zone_not_entitled | Outside the viewer's zones |
| title_required / bad_zone / bad_state / bad_source / bad_scoreboard | Validation |
| illegal_transition | Lifecycle skip |
| rights_unavailable | Need active rights |
| production_not_ready | No fresh heartbeat |
| not_live | media/end on a non-live event |
| invalid_ingest_token / ingest_scope | Encoder credential wrong |
| bad_service_key | Wrong media service key |
| subscription_inactive | Entitlement |
| package_not_entitled | Entitlement |
| destination_not_allowed | Entitlement |
| not_playable | Status not live/replay/archive |
| mode_mismatch | Lease mode vs live state |
| window_not_open / window_closed | Rights window |
| invalid_lease / event_mismatch / unknown_subject / rights_version_changed | Lease re-check |
| no_lease | Media request without cookie |
| verification_unavailable | Treasure required outside demo |
| member_unavailable | complete_auth unknown user |
| entitlement_denied | Inactive account/subscription at member login |
| verification_required | Member session's Treasure record dead |
| archive_not_found / archive_not_authorized | Archive playback |
| playback_denied | Member-safe wording for failed lease |
| audit_not_found | Unknown AUD- id |
| ai_disabled | AI flag off (503) |
| ai_error | AI handler exception |
| bad_path | AI/media path escape |
| studio_error | FFmpeg cut failure |
| private_live_capture_disabled | L1B flag off (503) |
| illegal_live_session_transition | L1B state machine |
| idempotency_conflict | L1B idempotency reuse mismatch |
| forbidden_origin | CORS/WS origin |
| body_too_large / bad_json / not_found / internal | HTTP surface |
| malformed token / bad signature / undecodable payload / wrong token type / expired token | TokenError strings |

WebSocket close: 1008 origin/path/token/zone/rate; 1013 per-IP limit.

---

## Config and flags

Primary reference: `config.example.env` and `backend/config.py`.

### Core

| Variable | Default | Meaning |
| --- | --- | --- |
| TZ_ENV | development | demo/local/development allow Treasure simulation; production is strict |
| TZ_HTTP_HOST / TZ_HTTP_PORT | 127.0.0.1 / 8000 | HTTP bind (`PORT` on Render) |
| TZ_WS_HOST / TZ_WS_PORT | 127.0.0.1 / 8765 | Socket bind (disabled as separate listen on Render) |
| TZ_ALLOWED_ORIGINS | derived from HTTP | Exact CORS and WS Origin |
| TZ_DATABASE_PATH | data/three_zone.sqlite3 | SQLite file |
| TZ_DATABASE_URL | empty | Postgres when set |
| TZ_DATA_DIR | data | Data root |
| TZ_TOKEN_SECRET | demo string | HMAC for session/lease/ingest |
| TZ_MEDIA_SERVICE_KEY | demo string | Media proxy and media/end |
| TZ_SESSION_TTL | 3600 | Seconds |
| TZ_PLAYBACK_LEASE_SECONDS / TZ_LEASE_TTL | 60 | Seconds (capped at 60) |
| TZ_INGEST_TTL | 21600 | Seconds |
| TZ_HEARTBEAT_TIMEOUT | 12 | Seconds |
| TZ_SEED_PASSWORD_* | change-me-*-local | Demo accounts |

### Media

| Variable | Default | Meaning |
| --- | --- | --- |
| TZ_LIVE_MEDIA_PROVIDER | demo | demo \| cloudflare |
| TZ_MEDIA_PROVIDER | demo | Legacy alias |
| TZ_UGC_MEDIA_PROVIDER | fake | fake \| cloudflare |
| TZ_PUBLIC_BASE_URL | derived | Public base |
| TZ_CLOUDFLARE_* | empty | Live Stream credentials |
| TZ_PHOTO_STORAGE | fake | fake \| s3 |
| TZ_PHOTO_S3_* | empty | Object storage for photos |
| TZ_MAX_POST_VIDEO_SECONDS | 90 | UGC limits |
| TZ_MAX_GAME_CLIP_SECONDS | 60 | Clip limits |
| TZ_VIEWER_HEARTBEAT_INTERVAL_SECONDS | 15 | Measurement |
| TZ_VIEWER_STALE_AFTER_SECONDS | 90 | Measurement |

### Moten / XRPL

| Variable | Default | Meaning |
| --- | --- | --- |
| TZ_MOTEN_SERVICE_URL | empty | Moten base URL |
| TZ_MOTEN_SHARED_SECRET | empty | Outbound auth |
| TZ_MOTEN_TIMEOUT_SECONDS | 5 | HTTP timeout |
| TZ_XRPL_MODE | demo | demo vs stricter |
| XRPL_RPC_URL / TZ_XRPL_RPC_URL | empty | Production required |
| XRPL_NETWORK | empty | Production required |
| XRPL_AUDIT_ACCOUNT / TZ_XRPL_ACCOUNT | empty | Production required |
| XRPL_SIGNING_SECRET / TZ_XRPL_SIGNING_SECRET | empty | Production required; never public |
| XRPL_KEY_ID | empty | Production required |
| TZ_XRPL_PUBLICATION_MODE | batch | batch settings |
| TZ_XRPL_BATCH_MAX_RECORDS | 500 | Batch |
| TZ_XRPL_BATCH_MAX_AGE_SECONDS | 3600 | Batch |

### AI (default OFF)

| Variable | Default | Meaning |
| --- | --- | --- |
| THREEZONE_AI_ENABLED | false | Process kill switch |
| THREEZONE_AI_CONFIG | package default YAML | Overlay path |
| THREEZONE_AI_LINEAGE_PATH | data/lineage.jsonl | Lineage store |
| THREEZONE_AI_LINEAGE_BACKEND | jsonl | jsonl \| sqlite |
| OLLAMA_* / LOCAL_WHISPER_MODEL | local defaults | Local-first |
| GROQ_* / GEMINI_* / CLOUDFLARE_* (AI) | empty | Optional overflow |

### L1B / future live (default OFF)

| Variable | Default | Meaning |
| --- | --- | --- |
| THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED | false | L1B operator private capture |
| THREEZONE_MEMBER_LIVE_ENABLED | false | Not implemented in L1B |
| THREEZONE_SPORTS_VERIFY_ENABLED | false | Not implemented in L1B |
| THREEZONE_LIVE_PUBLICATION_ENABLED | false | Not implemented in L1B |
| THREEZONE_LIVE_CONTINUOUS_VERIFY_ENABLED | false | Not implemented in L1B |

`run.py --http-port --ws-port --host` override binds.

Public config JSON: env, ws_url_base, session_ttl, lease_ttl, heartbeat_timeout, zones, simulation boolean, register_enabled — never signing secrets or API keys.

---

## Source files

**three-zone-mvp/**

- `run.py` — process supervisor
- `THREE_ZONE_MASTERY.md` — this article
- `README.md` / `SECURITY.md` / `PRODUCTION.md` / `RUN_TONIGHT.md` — ops docs
- `config.example.env` — copy-paste env including AI and L1B flags
- `requirements.txt` / `Dockerfile` / `render.yaml`
- `backend/config.py` — env, production refusal, live flags
- `backend/db.py` — schema
- `backend/passwords.py` — PBKDF2
- `backend/tokens.py` — HMAC tokens
- `backend/seed.py` — demo users and events
- `backend/control_plane.py` — authority (lifecycle, rights, leases, cameras, inventory)
- `backend/portal.py` — member, Treasure, schedules, XRPL publish
- `backend/http_server.py` — HTTP/CORS/CSP/cookies/routes
- `backend/ai_gateway_routes.py` — `/api/ai/*` mixin
- `backend/live_sessions.py` — L1B private live
- `backend/moten_adapter.py` — Moten outbox
- `backend/network.py` / `huddle.py` — member network + friends/parties
- `backend/ws_server.py` — socket hub
- `backend/demo_media.py` / `media_provider.py` / `media_providers/*` — media rails
- `backend/camera_*.py` / `photo_storage.py` / `pipeline.py` / `merkle.py` / `xrpl_adapter.py`
- `backend/mastery.py` — this article → HTML
- `backend/static/*` — member + ops UI
- `threezone_ai/` — gateway, providers, lineage, studio_ffmpeg, vision (V0 library)
- `scripts/ingest_heartbeat.py` / `live_readiness.py` / `smoke_walkthrough.py`
- `tests/test_*.py` — contract tests

**repo root**

- `index.html` — Moten IP control plane
- `timezone-clock.html` — unrelated clock
- `docs/` — phase plans, multi-AI notes, security baselines

---

## Tests

Test modules under `three-zone-mvp/tests/` (non-exhaustive of assertions, complete of files):

| File | Locks |
| --- | --- |
| `test_control_plane.py` | Lifecycle, rights, leases, roles, ingest, media/end |
| `test_portal.py` | Member auth, Treasure, schedules, XRPL order |
| `test_ai_gateway_fail_closed.py` | Process kill switch / no_ai |
| `test_ai_gateway_routes_disabled.py` | HTTP AI 503 when flag off |
| `test_live_sessions_l1b.py` | L1B states, strip truth, flag off |
| `test_sports_vision_v0.py` | Vision library-only contracts |
| `test_moten_integration.py` | Outbox delivery; Moten `accepted` body |
| `test_network.py` / `test_huddle.py` | Network + friends/parties |
| `test_camera.py` / `test_cloudflare_media.py` / `test_media_pipeline.py` | Cameras and media rails |
| `test_ops_dashboard.py` / `test_public_site.py` / `test_public_inputs.py` | Ops + public surfaces |
| `test_render_health.py` / `test_render_layout.py` | Render health/layout |

Important promises:

- Live lease issues and validates for a midwest viewer; west is `zone_not_entitled`
- Revoke invalidates lease; restore is new version; old lease is `rights_version_changed`
- Illegal lifecycle skip rejected; green/live need heartbeat
- media/end needs the service key
- AI routes disabled by default; gateway.run fail-closed without process flag
- L1B disabled by default; cannot publish / Restream / AI
- Canonical audit exists **before** simulated XRPL `VALIDATED` receipt
- Moten handoff stores delivered + Moten acceptance body without claiming human AI review
- Inventory is owner-only and never leaks token secrets

---

## Simulated vs not built

**Simulated in demo:** Treasure VERIFIED receipts, XRPL publications (`DEMO-` tx ids), local color-bar MP4, Moten IP browser localStorage workflows, fake UGC upload provider, V0 vision fake providers.

**Gated OFF by default (code exists):** AI Gateway HTTP + `gateway.run`, L1B private live sessions, future member-live / sports-verify / live-publication / continuous-verify flags.

**Real in this MVP:** lifecycle guards, rights versions, entitlement, HMAC tokens, lease cookies, media re-validation, ingest failover, socket origin/token limits, hash-chained audit, password login, role gates, owner print, member catalog, member network, Moten outbox, Cloudflare live seam, settlement measurement tables.

**Not built yet (do not pretend they are):** live XRPL submit client, OIDC, TLS termination (platform), managed Redis/NATS/Kafka fan-out, full managed SRT/HLS/CDN kill switch, KMS, WORM SIEM, youth privacy review, counsel-reviewed production rights desk, TZ-02 opportunity ranking, TZ-05 money settlement payouts, full TZ-06 relationship graph, email verification, password reset, self-service staff accounts, Moten three-human AI review, Moten R1/R2/signer lineage, gray-gate Treasure AI packet automation, public Restream from L1B, V0 vision HTTP.

This is an executable pilot of the critical loop, not a claim that a laptop process is a national broadcast network.

---

## End-to-end walkthroughs

### A. Family watches a midwest game

1. Owner or worker creates an event (or uses seeded `evt_mw_basketball`). Rights v1 exists. Status `scheduled`.
2. Encoder receives an ingest token for primary (and optionally backup). Heartbeats keep last-seen fresh.
3. Worker walks gray → yellow → green. Green is blocked until heartbeat is fresh. (Gray is human-walked; no AI packet clears it yet.)
4. Worker moves green → live. Families entitled in that zone see it on Live.
5. Member signs in. Treasure (demo) verifies. Cookie + Bearer issued. Watch issues a ≤60-second lease cookie. Video bytes are re-checked.
6. Socket streams score and feed health. Worker may update score.
7. If rights are disputed, worker revokes. Player gets `rights.revoked`. Next media request is 403. Restore creates v2. Old leases stay dead.
8. When the game ends, media service (or worker) moves live → replay. Then later archive.
9. Every step appends operational audit. Member/portal steps also append hash-chained `audit_events`.
10. Operator publishes pending hashes. Demo writes XRPL simulator rows.

### B. Operator private capture (L1B)

1. Ensure `THREEZONE_PRIVATE_LIVE_CAPTURE_ENABLED=true` in a non-production experiment only if authorized.
2. Operator `POST /api/live-sessions` with optional event_id / idempotency_key.
3. Server forces LIVE_PRIVATE + distribution DISABLED; advances to VERIFYING_PRIVATE.
4. Operator previews locally. Browser source is **not** published. No Restream, no AI, no Moten intake.
5. Operator `POST …/stop` → STOPPED. Audit rows only.

### C. AI caption when deliberately enabled

1. Set `THREEZONE_AI_ENABLED=true` and configure Ollama (or overflow keys). Restart.
2. Member `GET /api/ai/status` shows `enabled: true` and gateway summary.
3. Member `POST /api/ai/transcribe` with `asset_ref` under media policy.
4. Optional `POST /api/ai/lineage/edit` then `…/lineage/approve` writes **local** lineage only — not Moten review.

### D. Moten evidence handoff

1. Configure `TZ_MOTEN_SERVICE_URL` + shared secret.
2. Operator `POST /api/moten/intake/event` with `event_id`.
3. Job moves queued → delivered. Moten may respond `accepted: true` meaning **packet received**.
4. Three-Zone lifecycle and rights are unchanged by that acceptance.

That is every major engine, every API group, and the honest gaps, in the order a human actually uses them.

---

## Seeded events (first run)

| event_id | Title | Zone | Status | Mode | Notes |
| --- | --- | --- | --- | --- | --- |
| evt_mw_basketball | Lincoln Freshman Basketball | midwest | live | single_camera | Fresh primary; score 34-29 Q3 05:12 |
| evt_mw_volleyball | Lakeside Volleyball | midwest | green | multi_camera | Cleared, not live |
| evt_mw_soccer | Prairie Soccer Semifinal | midwest | live | backup_active | Fresh **backup** |
| evt_mw_hockey | Northside Hockey | midwest | green | single_camera | Ready to go live |
| evt_mw_wrestling | Central Wrestling (Archive) | midwest | archive | single_camera | replay_available; member archive card |
| evt_w_football | Coastal Football | west | scheduled | multi_camera | Viewer cannot watch (zone) |
| evt_w_baseball | Harbor Baseball (Replay) | west | replay | single_camera | Viewer denied by zone |
| evt_e_lacrosse | Metro Lacrosse | east | yellow | single_camera | In clearance; east |

If events already exist, seed will not duplicate them. Demo users are always upserted. Legacy `demo-admin` is deleted.

---

## Security headers and CORS

Every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, Content-Security-Policy `default-src 'none'` with script/style/img/media `'self'`, `connect-src 'self'` plus the configured `ws://` or `wss://` origin, `base-uri 'none'`, `form-action 'self'`, `frame-ancestors 'none'`.

API and media: `Cache-Control: no-store`.

CORS: exact origin match from `TZ_ALLOWED_ORIGINS`, credentials true, never `*`. OPTIONS allows GET, POST, headers Authorization, Content-Type, X-Media-Service-Key.

Production also requires token secret ≠ media key, both ≥ 32 chars, not demo values, origins set, XRPL complete, seed passwords not demo.

See `SECURITY.md` for the socket threat table and launch gates (OIDC, TLS, Postgres, durable bus, managed CDN, KMS, WORM SIEM, youth privacy, counsel-reviewed rights).

---

*End of Three Zone Mastery. Print from Owner → Mastery. Live numbers print from Owner → Inventory.*
