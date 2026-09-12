# Semgrep baseline — THREEZONE (2026-09-12)

**Scope:** `three-zone-mvp/backend` + `three-zone-mvp/threezone_ai`  
**Tool:** Semgrep CLI `1.177.0` (`--config=auto`)  
**Lane:** Independent security review (Snyk + Semgrep). Builder did not certify.

## Summary

| Severity | Count |
|----------|------:|
| ERROR | 5 |
| WARNING | 6 |

Raw JSON: `/workspace/PHASE0/security-reports/semgrep-backend.json` (local agent artifact; not required in prod).

## ERROR triage

| Finding | Location | Disposition |
|---------|----------|-------------|
| Insecure WebSocket (`ws://`) | `backend/config.py` `public_config` | **FIXED** — use `wss://` when production or `public_base_url` is https |
| SQL string concat | `control_plane.py` heartbeat column | **FIXED** — explicit allowlisted `UPDATE` statements (no dynamic column from client) |
| SQL string concat | `db.py` schema migrator `ALTER TABLE` | **ACCEPTED RISK** — column names from hardcoded `event_alters` map only |
| SQL string concat | `db.py` `execute` RETURNING append | **ACCEPTED RISK** — only when inserting into `audit`, not user SQL |
| SQL string concat | `live_sessions.py` transition `SET` | **ACCEPTED RISK** — column names from code-controlled `ts_field` / `extra_sets` keys; values parameterized |

## WARNING triage

| Finding | Disposition |
|---------|-------------|
| Formatted SQL (`db.py` ALTER) | Same as migrator accepted risk |
| Dynamic urllib (`live_readiness`, `media_provider`, `cloudflare`, `moten_adapter`, `xrpl_adapter`) | **ACCEPTED RISK for now** — URLs from config/provider, not raw client path. Track for https-only / SSRF allowlists in a later ticket |

## Snyk

Snyk connector is installed. CLI auth timed out in agent session — **Andre must complete Snyk sign-in** once, then re-run SAST/SCA. Until then Semgrep is the active offline scanner.

## Governance note

Findings here are **evidence**, not publication authority. Remediation acceptance stays with human/Treasure review for consequential changes.
