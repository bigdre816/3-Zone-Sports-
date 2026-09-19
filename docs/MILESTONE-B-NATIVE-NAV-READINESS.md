# Milestone B — Native navigation readiness

Milestone B is **not implemented**. This is a readiness assessment only. Milestone A (Getting There planning) must stay in the City plane; native turn-by-turn is a later, separate `NavigationService` capability.

Do not treat a maps URL, a planning polyline, or a web “start” button as `navigation.started`.

## Status

| Gate | Status | Notes |
| --- | --- | --- |
| BUILT | **no** (capability stub only) | `NavigationService.capability()` returns `native: false`. No SDK, no plugin, no session. |
| TESTED WITH FIXTURES | **partial** | Stub asserts `native=false` and forbids `navigation.started` / `navigation.arrived` emission from planning. No native fixtures. |
| VERIFIED WITH LIVE PROVIDER | **no** | Navigation SDK was not called. |
| VERIFIED ON PHYSICAL DEVICE | **no** | No iOS/Android project in this repo. |
| PRODUCTION CONFIGURED | **no** | Navigation SDK billing, API restrictions, signing, and store credentials are unset here. |
| PRODUCTION VERIFIED | **no** | Not claimed. |

## What exists today (A only)

- Server-side traffic-aware **planning** against `city_place_id`
- External Google Maps directions URL helper that **does not** emit `navigation.started`
- Signal vocabulary that reserves `navigation.started` and `navigation.arrived` for native evidence

## Blockers for B

1. **Navigation SDK Android** — not in this repository; no Gradle/module, no Nav SDK dependency, no in-app guidance UI.
2. **Navigation SDK iOS** — not in this repository; no Xcode project or CocoaPods/SPM Nav SDK integration.
3. **Capacitor plugin** — Capacitor lives in the Lovable Member Gateway (separate). This repo has no `capacitor.config`, `ios/`, or `android/`. A plugin would wrap SDK start/stop/arrive and call the backend with evidence ids only.
4. **Billing / Maps platform products** — Routes (A) and Navigation SDK (B) are different products. A Routes key does not imply Navigation SDK entitlement. Dashboard enablement is unverified.
5. **Signing** — no upload keystore, no Apple distribution cert/profile in this repo.
6. **Physical device** — no verified device session. Emulators are not production verification for turn-by-turn.

## Config names relevant later (no secret values)

| Name | When needed |
| --- | --- |
| `GOOGLE_MAPS_API_KEY` / `GOOGLE_ROUTES_API_KEY` | Already reserved for A planning |
| Navigation SDK / Cloud project restrictions | B — not wired |
| Capacitor / native app identifiers | B — Lovable / mobile repo, not here |

## Signal rule that B must keep

| Signal | Who may emit |
| --- | --- |
| `directions_requested` | Explicit member request (A already) |
| `navigation.route_ready` | Usable planning or native route object with evidence |
| `navigation.started` | Native SDK session start only |
| `navigation.arrived` | Native SDK arrival only |

Web, planning, and the external maps URL remain forbidden sources for started/arrived.

## Suggested B sequence (not built)

1. Confirm Navigation SDK billing and package restrictions on the Cloud project.
2. Add a Capacitor plugin in the member app repo (not this backend).
3. Android + iOS signed device builds.
4. Backend endpoint that **records** started/arrived from the plugin with ids, no raw breadcrumbs in analytics.
5. Device verification, then production configuration, then production verification — claim each gate only when true.
