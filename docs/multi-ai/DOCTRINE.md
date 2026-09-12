# THREEZONE multi-AI doctrine

**Rule one:** The AI that creates the work does not certify the work.

Treat models like separate employees. CI is the referee. “Looks good” from an AI is not evidence.

## Pipeline (every meaningful change)

```
Requirement
  → Spec AI (acceptance + failure cases + must-not-change)
  → independent acceptance tests (from Spec, not Builder rationale)
  → Builder AI (code/PR only)
  → automated tests (Test AI designs to break the feature)
  → Reviewer AI (diff + spec)
  → Security AI (auth/roles/secrets/leak)
  → Adversary AI (abuse/bypass/break)
  → Release AI (staging + evidence pass/fail)
  → Human approval (final merge/activation)
  → deploy smoke (/healthz, auth, critical flows)
  → GREEN only after proof
```

## Roles

| Role | Gets | Must produce |
|------|------|----------------|
| Spec | Problem only | Acceptance criteria, failure cases, what must not change |
| Builder | Spec + repo | Code/PR only — no self-certification |
| Test | Spec (prefer hide Builder reasoning) | Unit/integration/regression tests designed to break the feature |
| Reviewer | PR diff + spec | Bugs, logic errors, drive-by changes, missed edges |
| Security | PR + permission model | Auth/role/rights/secret/data-leak findings |
| Adversary | Running behavior / requirements | Bypass and abuse attempts |
| Release | Staging + acceptance | Pass/fail with evidence |
| Human | All reports | Merge/activation authority |

## Model sizing

- Small **local** models (Ollama): repetitive static checks, test stubs, gateway import bans
- Stronger models: architecture, security reasoning, weird failures, hard diffs

## Product invariants (never LLM-owned)

- Official score, clock, rights state, settlement truth
- Live games must work when **every** AI provider is dead
- All generative AI → **AI Gateway only** (local → overflow → fallback → no-AI)
- AI captions/descriptions carry lineage: source → model/version → output → human edit → approved

## Treasure evidence language (Y1c)

Transport receipt into Moten/control-plane intake is **not** Treasure Path A release.
See [TREASURE-EVIDENCE-VOCABULARY.md](./TREASURE-EVIDENCE-VOCABULARY.md) (G0-C locked).
