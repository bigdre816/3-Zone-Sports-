# Y4 — Local transcription + immutable proposal

**Scope:** Local-first transcription path (`transcription_local`) and an append-only
**transcription proposal**. Depends on Y3 `ai_jobs`.

## Proposal ≠ Treasure release

Creating a proposal (`status=proposed`, `schema_ref=threezone.transcription.proposal.v0`)
does **not**:

- publish content (`publish=false`)
- release to Treasure (`treasure_release=false`)
- complete Path A review / Moten institutional release
- mutate ControlPlane rights, playback leases, score, settlement, or XRPL

Treasure delivery / reconciliation is **Y5**. Human review seats are **Y6**.
Member panel is **Y7**.

## Local path

Gateway default order for `transcription`:

1. `transcription_local` — `is_local=True`; deterministic segments in CI; optional
   faster-whisper only when installed and media exists; never Groq/Gemini
2. `transcription_offline` — pure fake fallback (Y2)

## Immutability

Proposals live in isolated SQLite (`data/ai_proposals.sqlite`, table `ai_proposals`).
Payload + `content_hash` (sha256 of canonical segments JSON) are **append-only**.
Updates to payload/hash raise `ProposalImmutable`. `verify_hash()` detects tampering.

## Emit

- `AiJobService.propose(job_id)` after a succeeded transcription job
- `POST /api/ai-jobs/{id}/propose` (operator)
- Optional auto-propose when the process job service is configured with a propose store
