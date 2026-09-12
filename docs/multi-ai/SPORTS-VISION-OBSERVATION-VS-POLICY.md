# Sports vision: observation ≠ policy ≠ publication

**Ticket:** V0 / P1-V0 (Rev 2) — synthetic / offline library only
**Status:** Doctrine note. Not a product enablement. Not an HTTP contract.

## The line

| Layer | Owner | May say | Must not say |
|-------|--------|---------|--------------|
| **Observation** | Model / provider (fake in V0) | “I saw a hoop, hardwood, basketball, nine people moving across these frames.” | `publish`, `approved`, `rights_valid`, `sports_status=verified`, `eligible_for_rights_check` |
| **Policy** | Deterministic THREEZONE code (`SportsContextPolicy`) | `eligible_for_rights_check` \| `hold_uncertain` \| `reject_non_sports` plus `reason_codes` | That a game is official, that rights exist, that a score is true |
| **Publication** | Existing ControlPlane / humans / later tickets | Rights grant, lease mint, restream, settlement | Anything an AI observation object requested |

A model that writes `publish: true` has described **nothing authoritative**. Validate strips structured authority fields and records `ignored_model_authority_field`. Policy is unaffected.

Natural language inside `signals[]` (for example “hardwood court visible”) is evidence language, not a decision. Poison is **structured keys**, not a blanket word filter.

## Objects

1. `SportsVisionEvidenceBundle` — immutable observation record (schema `threezone.vision.evidence.v0`). Reconstructable: source asset id + hash, sampled frame ids/hashes/timestamps, detections, scene signals, optional fake-escalation addendum, server-derived privacy class, content hash.
2. `SportsContextPolicyResult` — THREEZONE-owned decision bound to `evidence_bundle_id` and `source_asset_hash_checked`. Schema `sports-context-policy.v0`.

Hash mismatch between detect-time asset hash and policy-time hash → **hold / fail closed**. Frame hash mismatch → **hold / fail closed**.

## Sampling clocks (do not collapse)

| Clock | V0 rule |
|-------|---------|
| Source capture | Synthetic catalog asset as-is |
| Evidence sampler | **8–12 frames** across ~**20 seconds** (uniform inclusive endpoints). Documented in `EvidenceSampler`. |
| Detector / scene | Run **only** on sampled frames |
| Continuous FPS | **Forbidden** in V0 (that is a later live ticket) |

## What V0 does not do

- No product HTTP route, worker admission, or gateway task registration
- No real Gemini / Groq / Ollama / Rekognition / Cloudflare AI calls
- No YOLO vs RF-DETR brand lock
- No Moten / Treasure / ControlPlane mutation
- No production AI enablement
- No DB migrations
- `eligible_for_rights_check` does **not** invoke rights, lease, score, settlement, or XRPL

Y1b fail-closed (`process_ai_enabled`, Settings default false) is verified on this worktree. V0 remains library-only **by design** until a later ticket deliberately registers a product path.

## Privacy and path safety

- Requests accept `source_asset_id` only (`asset:synthetic:…`).
- Reject filesystem paths, `file://`, and `http(s)://`.
- Privacy class is **server-derived**. Client spoof cannot force cloud escalation.
- P2 is local-only; V0 escalation is `FakeEscalationProvider` only.
- P3 → reject processing.

## License gate

Real Layer-1 / Layer-2 weights are blocked until framework license, weight license, commercial-use status, distribution obligations, verification date, and reviewer are recorded. Until then, only fake providers may run in CI.
