# Vision detector bakeoff (V1-bakeoff / G3-D)

**Status:** Metrics harness + license gate recorded. Not a production enablement.  
**Code:** `threezone_ai/vision/bakeoff.py`

## Line

| Claim | Allowed? |
|-------|----------|
| Run stub detectors on the V0 labeled synthetic corpus | Yes (CI) |
| Record recall / FP / obstruction / latency / memory / license / offline | Yes |
| GREEN a candidate after license gate + metrics | Report only |
| Popularity or brand name ⇒ GREEN | **No** |
| Auto-switch production Layer-1 detector from bakeoff | **No** |
| Download / ship unlicensed weights | **No** |

## License gate

A candidate **cannot** receive verdict `GREEN` when:

1. `license_status` ∈ `{unlicensed, unknown}`, or
2. `offline_capable` is false while `offline_required` is true.

Gate reason is recorded on the candidate metrics object (`gate_reason`).

Permissive / restricted statuses may proceed past the license gate; GREEN still does **not** flip `THREEZONE_AI_ENABLED` or change the production detector.

## CI stubs

- `stub_high_recall` / `stub_precise` — behavior-profile fakes (permissive, offline).
- Optional named stubs `stub_yolo_like` / `stub_rfdetr_like` — **names only**; not brand locks; default metadata keeps them non-GREEN until a real license record exists.

No network. No weight download.

## Out of this ticket

V1-train (G3-E), V1-Gemini-Pilot (G3-F), prod AI flip, Restream / LIVE_PUBLIC / Treasure release.
