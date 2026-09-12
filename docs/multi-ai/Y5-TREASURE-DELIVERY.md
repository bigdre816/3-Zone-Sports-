# Y5 — Treasure delivery + reconciliation

**Scope:** Canonical Treasure **delivery + reconciliation** for immutable
transcription proposals (Path A **producer → evidence lane** plumbing).

**Depends on:** Y4 local transcription proposals, Y1c vocabulary, Moten outbox
adapter patterns.

## Intent (Andre / G0-C)

Prepare **THREEZONE to talk to Treasure Network with all required information**.

This ticket does **not** build Treasure’s Path A 4-seat review (R1 / R2 / Release)
inside THREEZONE. Canonical evidence **packet / revision**, review history, and
**release** stay in Treasure.

| Layer | Owner |
|-------|-------|
| Evidence proposal, hashes, provenance, outbox, delivery receipts | **THREEZONE** |
| Canonical packet / revision, dual review, release authority | **Treasure** |

## Delivery ≠ release

- Successful transport is recorded locally as **`intake_accepted`** (transport receipt into Moten/control-plane intake only).
- Bare product language **`accepted` is banned for governance**.
- `treasure_release` stays **`false`** in THREEZONE; delivery never flips it.
- Moten is an **adapter / outbox name only**, not a Treasure department.

## Producer handoff packet

Schema: `three-zone.moten.transcription-proposal.v1`
(alt: `threezone.treasure.proposal.delivery.v0`)

Required Path A producer fields for this slice:

| Field | Value / notes |
|-------|----------------|
| `packet_family` | `THREEZONE` |
| `packet_type` | `THREEZONE_MEDIA_TRANSCRIPT` |
| `proposal_id`, `job_id`, `source_asset_id` | from Y4 proposal |
| `content_hash` | sha256 of canonical segments |
| `segments` / `segments_ref` | full segments + stable ref |
| `proposal_schema_ref` | `threezone.transcription.proposal.v0` |
| `lineage` | provider / model / version when available |
| `producer` | identity fields as available (`role=producer`) |
| `publish` | always `false` |
| `treasure_release` | always `false` |
| `canonical_*` | projections only when Treasure returns them — never invented seats |

Delivery-state vocabulary (THREEZONE side):

`submitted` → (`queued_for_delivery`) → **`intake_accepted`** (transport)

Projections may later show `canonical_packet_id` / `canonical_revision_id` /
`canonical_status`. THREEZONE must **never invent** Reviewer 1, Reviewer 2, or
Release Authority seats.

## Outbox

Table `treasure_delivery_outbox` (isolated AI proposals SQLite; not ControlPlane
sports truth). Statuses:

| Status | Meaning |
|--------|---------|
| `pending` | Proposal exists; no delivery attempt yet (reconcile view) |
| `queued` | Moten enabled; awaiting / in transport |
| `skipped` | Moten disabled — honest fail-closed |
| `failed` | Transport error |
| `intake_accepted` | Treasure/Moten intake received payload (transport only) |
| `mismatch` | Local proposal hash ≠ last receipt hash |

Idempotent redelivery: a second `deliver` for the same `proposal_id` +
`content_hash` returns the existing `intake_accepted` receipt.

`MotenIntakeService.handoff_transcription_proposal` mirrors the same handoff
type on the control-plane Moten outbox when operators use that path.

## Operator API

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/api/ai-proposals/{aip_…}/deliver` | Fail-closed `skipped`/503 if Moten disabled |
| `GET` | `/api/ai-proposals/{aip_…}/reconcile` | pending vs intake_accepted vs failed/… |
| `GET` | `/api/ai-proposals/{aip_…}` | proposal fetch |

Env: `TZ_MOTEN_SERVICE_URL`, `TZ_MOTEN_SHARED_SECRET`, `TZ_MOTEN_TIMEOUT_SECONDS`
(same as Moten adapter). Optional outbox path:
`THREEZONE_TREASURE_DELIVERY_PATH` (defaults to proposals sqlite).

## Out of scope (later tickets)

- **Y6** independent review engine / immutable revisions product
- **Y7** member panel
- Full Treasure Path A 4-seat product UI
- Prod AI flip; Restream / `LIVE_PUBLIC`; rights / score / settlement / XRPL mutation

## Implementation map

- `threezone_ai/proposals/delivery.py` — payload builder, outbox, deliver, reconcile
- `backend/moten_adapter.py` — `handoff_transcription_proposal` + `intake_accepted` status
- `backend/ai_gateway_routes.py` — operator deliver / reconcile routes
- `tests/test_y5_treasure_delivery.py`
