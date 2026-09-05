# AGENTS.md — Moten IP & Invention Control Plane

> Governing operating rules for any human or AI agent working in this repository.
> These rules are derived from the **Moten IP & Invention Control Plane — Master
> Specification V1.0** (frozen), which is the canonical architecture for this system.

## 0. Canonical source of truth

- The governing document is `docs/Moten_IP_Invention_Control_Plane_Master_Specification_v1_0.pdf` (V1.0, frozen).
- Its recorded SHA-256 is in `docs/SPEC_MANIFEST.md`. If the file hash changes, that is a **new version** — never edit V1.0 in place (see §2).
- When this file and the spec disagree, the spec wins. Fix `AGENTS.md` to match, and note the correction.
- Phase 1 scope and design are in `docs/phase-1-plan.md`. Phase boundaries there are binding: do not build later-phase services early (see §7).

## 1. The operating sentence

> Be first to recognize it. Be disciplined enough to document it. Be fast enough to file it. Be smart enough to know what not to disclose.

This system exists to capture the whole transformation — question → observation →
insight → mechanism → embodiment → evidence → human contribution → IP decision →
disclosure control → filing → implementation → future improvement — and to keep four
histories **linked without confusing them**:

1. **Provenance** — what was observed, when, which version existed, who contributed.
2. **Legal filing** — what was filed, the USPTO-verified date, named inventors, supported subject matter, deadlines.
3. **Runtime enforcement** — the rights/identity/privacy/security/settlement rules enforced in real time.
4. **Portfolio governance** — whether a mechanism is protected by patent, trade secret, both, or neither, and why.

## 2. The control-plane constitution (non-negotiable)

These are hard invariants. Code, schemas, APIs, and workflows must enforce them; they are not merely documentation.

1. **Date is a control, not a story.** Every date is labeled with its legal meaning: `internal provenance date`, `public disclosure date`, or `USPTO filing date`. An internal timestamp is **never** presented as a filing date. A Git commit, hash, recording, or research date supports provenance only — `legal_effect: "provenance_only"`.
2. **Version history never disappears.** A changed question, mechanism, rights grant, policy, formula, or settlement rule creates a **new immutable version** and preserves the old one. No destructive edits, ever. Corrections are compensating events, not in-place mutations. Wrong records are marked `superseded | corrected | withdrawn | rejected` with a reason — never deleted.
3. **Mechanism beats slogan.** No invention advances to counsel without inputs → transformation → outputs, alternatives, technical context, failure behavior, and evidence. Reject business descriptions ("a platform that uses surveys to pick sports"); accept testable technical system hypotheses.
4. **Humans own conception.** The record describes what each **natural person** contributed. AI is captured as a tool (`inventor_status_of_ai: "tool_only"`) and can never be made an inventor by workflow automation.
5. **Public release is privileged.** No public or partner release bypasses IP preflight, secrecy classification, or required approval.
6. **Rights bind the runtime.** Existence in a database does not make an event distributable. A current, signed rights lease must authorize the exact window, territory, destination, and use.
7. **Unknown means hold (fail closed).** Missing authority, stale policy, conflicting versions, an unverified contributor, or incomplete support produces a fail-closed status until resolved.
8. **The system proves process, not patentability.** Counsel decides inventorship, claim scope, prior art, filing strategy, ownership, and jurisdiction. Moten makes that work faster and more reliable — it does not render legal conclusions.

## 3. Legal guardrails baked into behavior

- **First-inventor-to-file:** earlier conception alone is not an earlier effective filing date. Preserve conception evidence, but push viable candidates toward counsel and filing.
- **Provisional clock:** track 12-month pendency from the **verified** filing date; require written description, drawings when needed, named inventors, and a support matrix.
- **Public disclosure:** record every proposed and completed disclosure; pre-filing public release defaults to hold unless counsel approves. The U.S. grace period is not the operating strategy and is not a foreign-rights strategy.
- **AI-assisted work:** record human contribution and AI assistance separately; only natural persons are inventors; a generated draft is never the ownership/inventorship record.
- **Trade secret:** preserve evidence of reasonable secrecy (labels, access rules, NDAs, training, logging, export controls, offboarding, incident response, review).
- **International:** PCT/foreign rights are a separate priority decision; do not assume a U.S. provisional protects every country.

Internal evidence **can** support chronology, contribution, which version existed, what was shown to whom under what confidentiality, and consistent secrecy controls. It **cannot** by itself establish a USPTO filing date, provisional benefit, patentability, legal inventorship, ownership, foreign priority, or trade-secret existence absent reasonable measures.

## 4. Plane boundaries — linked, never collapsed

Moten is a control plane **above** the operating companies (Three-Zone, Treasure, Passport, future). Preserve these six planes as real boundaries in implementation (separate ownership, storage, and access; link records, do not merge data):

| Plane | Contains | Accountable owner |
| --- | --- | --- |
| Signal | Longitudinal Research Registry, observations, interviews, experiments, demand signals, telemetry refs | Research steward, product owner |
| Invention | Mechanisms, invention families, embodiment packages, alternatives, diagrams, code/config refs, tests, claim nuclei | Inventor, technical lead, IP steward |
| Evidence | Hashes, signatures, event envelopes, time source, immutable versions, chain of custody, export manifests, legal holds | Security & records steward |
| Decision | Prior-art review, patent/trade-secret split, disclosure preflight, counsel decisions, ownership/assignment, risk acceptance | IP steward, counsel, founder |
| Runtime | Rights registry, entitlement, policy decision point, sockets, media objects, measurement, settlement, revocation | Engineering, security, rights ops |
| Vault | Unfiled invention detail, trade-secret material, restricted prompts/outputs, sensitive partner terms, credentials, keys | Security, counsel, named custodians |

**Hard rule:** "Governance above the companies" must not become one enormous unrestricted database. Linked ≠ collapsed. Each operating company keeps its own private runtime data boundary.

## 5. Canonical IDs and versioning

Every object gets an **immutable ID at creation** with a typed prefix:

`RQ` research question/instrument · `OBS` observation · `INV` invention candidate/family · `EMB` embodiment · `EVD` evidence artifact · `DISC` disclosure · `APP` patent application/filing · `TS` trade-secret asset · `RIGHTS` rights grant · `LIVE`/`LEASE` live session or event lease · `DEC` decision · `CAL` deadline/alert.

- Immutable content versions with a monotonically increasing revision number **and** a semantic label (`v1.0`, `v1.1`, `v2.0`).
- **Bitemporal** fields: `valid_from`/`valid_to` (intended applicability) and `recorded_at` (when Moten learned it).
- Every downstream decision stores **exact source version IDs** (e.g., a rights decision references a rights version and a policy version, not a mutable event ID).
- Split/merge are explicit relations that retain the parent and record the boundary decision.

**Canonical event envelope** (all state-changing events conform to this shape):

```json
{
  "event_id": "EVD-2026-004221",
  "event_type": "invention.version.committed",
  "object_id": "INV-2026-000017",
  "object_version": "2.1",
  "actor": {"person_id": "P-0001", "role": "inventor"},
  "recorded_at": "2026-09-05T14:20:31Z",
  "clock_source": "trusted-time-service",
  "payload_sha256": "<sha256>",
  "previous_event_hash": "<hash-or-null>",
  "attestation": "<signature>",
  "legal_effect": "provenance_only",
  "links": ["RQ-2026-000001", "OBS-2026-000184", "EMB-2026-000017-A"]
}
```

## 6. What AI agents in this repo MUST NOT automate

Per the constitution and USPTO AI-inventorship guidance, these actions require a human approval chain and must be **impossible to trigger by automation alone**:

- Adding, removing, or changing a named inventor.
- Moving an invention to `Filed`, `Publicly Disclosed`, or `Trade Secret Protected`.
- Granting a rights override, extending a media lease, disabling a kill switch, or changing a settlement formula.
- Exporting unfiled invention detail, trade-secret material, youth data, credentials, or partner-confidential terms to an unapproved model or destination.
- Treating a generated summary as the canonical invention record (AI output is draft/evidence until a human commits a version).
- Sending external communications that assert ownership, patentability, rights authority, or inventorship as a legal conclusion.

**AI gateway rule for this repo:** AI may organize, compare, draft, simulate, test, and suggest alternatives. Humans and policy engines execute. Record the human contribution matrix and an AI-interaction record (tool, model, purpose, prompt/output hashes, human action, `inventor_status_of_ai: tool_only`) for AI-assisted invention work.

## 7. Build discipline (irreversible-risk controls first)

Build in the spec's layered order. **Do not build later-phase services early.** Preserve interfaces for later phases without implementing them.

- **Days 0–30 (Phase 1 — current scope):** IDs, Research Registry, Invention Ledger, human-contribution form, disclosure preflight, filing calendar, counsel workbench, restricted storage. Exit evidence: one real candidate reconstructed end-to-end; no public-release bypass; deadlines visible.
- **Days 31–90:** hash manifests, append-only events, access policy, AI gateway, support matrix, first rights object, first counsel/prior-art review.
- **Months 3–6:** Policy Decision Point, rights leases, WebSocket gateway, ingest qualification, media-object metadata, revocation, audit/SIEM.
- **Months 6–12:** discovery graph, measurement facts, settlement ledger, partner adapters, WORM evidence, dashboards, operational drills.

Three-Zone runtime/media/security services and Treasure runtime are **out of Phase 1 scope**. Keep candidate families (TZ-01…TZ-06, TR-01…TR-06) as separate surfaces until technical evidence and counsel justify combining them.

## 8. Definition of done for changes in this repo

- The change names which plane(s) and which spec section(s) it implements.
- No constitution invariant (§2) is violated; version history is preserved; dates are labeled.
- New human/AI contribution is recorded where the change concerns invention work.
- Phase boundary (§7) is respected; later-phase surfaces are stubbed as interfaces only.
- Nothing secret/unfiled is disclosed in code, comments, fixtures, logs, or PR text without passing disclosure preflight.

## 9. Disclaimer

This repository implements a **process and evidence** system. It is not legal advice and does not determine patentability, inventorship, ownership, disclosure sufficiency, trade-secret status, privacy compliance, rights authority, or filing deadlines. Those require review by qualified counsel and responsible security/privacy professionals.
