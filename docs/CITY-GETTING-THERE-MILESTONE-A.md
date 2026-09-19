# THREEZONE City / Getting There — Milestone A

Status vocabulary is evidence-based: **BUILT** means committed code exists; **TESTED WITH FIXTURES** requires deterministic tests to pass; **VERIFIED WITH LIVE PROVIDER**, **VERIFIED ON PHYSICAL DEVICE**, **PRODUCTION CONFIGURED**, and **PRODUCTION VERIFIED** require separate evidence and are not implied here.

## Architecture findings

Repository inspection shows the signed-in member product is the `three-zone-mvp` Python/stdlib HTTP application with static HTML/CSS/JavaScript, a same-public-port WebSocket gateway, and the existing member session/authorization router. The production blueprint targets Render. `/api/member/sports` is present and marked `member` in the server route table, so sports access continues through the established server-side member gate.

No Capacitor configuration, `android/` native project, `ios/` native project, React Native project, or native signing configuration is present in this repository at this milestone. Therefore the owner-reported "Capacitor-capable" state is not repository-verifiable yet. A React Native migration is not justified: the existing web-first member application can be wrapped with Capacitor and a focused native plugin without replacing the application architecture.

## Milestone A implementation

`backend/city_route_planning.py` adds a provider-neutral `RoutePlanningService`, a Google Routes v2 adapter, and the canonical City place/event layer. `city_place_id` is the destination identity. Provider IDs and provenance are supporting evidence; similar names alone do not merge identities. A coordinate + normalized-name match is accepted only within a bounded proximity, while a known provider ID remains the stronger match.

`backend/city_http.py` attaches City routes to the existing handler so member/operator auth classes remain authoritative. The member endpoints are:

- `GET /api/member/city/config`
- `GET /api/member/city/places/{city_place_id}`
- `GET /api/member/city/events/{city_event_id}`
- `POST /api/member/city/getting-there`

Operator ingestion endpoints are `POST /api/admin/city/places` and `POST /api/admin/city/events`. The repository currently has no migration framework; City tables are created idempotently through the same database wrapper at first City service use. No separate authentication/session store is introduced.

`/city` is the milestone-A member experience. It supports manual origin or a one-time browser precise-location request after an explicit action. The screen does not start continuous tracking, does not store the current-location result, and does not put route origins into analytics. It shows a verified canonical destination, event-local time, editable early-arrival and parking/walking planning allowances, traffic-aware drive estimate, suggested departure, explanation, last successful estimate timestamp, and an external directions fallback. Embedded `Start Navigation` stays disabled because milestone B has not passed.

The departure calculation is:

`suggested_departure = desired_arrival - parking_or_walk_allowance - estimated_drive_duration`

For an exact event, desired arrival defaults to 10 minutes before start and parking/walking defaults to 10 minutes. A driving estimate is requested for now, then—only when the preferred departure is still in the future—rechecked once with Google Routes `departureTime` for that proposed future departure. The request count is capped at two. `arrivalTime` is not sent for driving. If the preferred departure is already past, the result is based on leaving now and reports estimated lateness against the arrival target.

## Location lifecycle at A

Discovery may continue using selected-city or approximate context. Getting There uses precise location only after `Use my location`; manual origin is always available. The first-use purpose copy is: “THREEZONE uses your location during navigation to provide directions, arrival estimates, and route progress.” Milestone A requests one location fix only. Continuous navigation location, background/locked-screen behavior, visible Stop Navigation, SDK cleanup, and navigation-session metadata do not begin until an explicit native `Start Navigation` exists in milestone B.

## Canonical signal vocabulary for the later telemetry gate

Milestone A does **not** claim backend navigation telemetry. The vocabulary reserved for milestone C is: `city.place_impression`, `city.place_opened`, `city.place_saved`, `directions_requested`, `navigation.route_ready`, `navigation.started`, `navigation.progress`, `navigation.rerouted`, `navigation.cancelled`, `navigation.arrived`, `navigation.failed`, and `offer.redeemed`.

Evidence rules remain strict: a browse-triggered route request is not automatically `directions_requested`; a Start button tap is not `navigation.started`; elapsed time is not route progress; and SDK arrival is a device-reported navigation outcome, not proof of venue entry, attendance, purchase, or independently verified physical presence. Legacy aliases must normalize into one canonical name and must not be double-counted.

## Milestone B native-navigation gate

Selected approach: **Capacitor 8 + a focused THREEZONE native navigation plugin**, keeping the existing web application as the product shell. No React Native migration is indicated by repository evidence. The native plugin should isolate vendor code behind a `NavigationService` interface while `RoutePlanningService` remains server/provider planning logic.

Target native SDK baselines to validate at implementation time:

- Android: Google Navigation SDK for Android 7.9.x baseline; current release notes show 7.9.0 in August 2026. Pin an exact supported version, not a floating range. Current 7.x requirements include modern Kotlin/Gradle/AGP and Android API support documented by Google.
- iOS: Google Navigation SDK for iOS 11.1.x baseline; current release notes show 11.1.0 in August 2026, with iOS 16 minimum and Xcode 26.x for the 11.x line. Pin an exact compatible version.
- Capacitor: v8 is the current documented major line. Create native `android/` and `ios/` projects only after the build environment is available, then implement the bridge through Capacitor's plugin interface.

Before B can be marked built/verified, the Google Cloud project must have billing enabled and the relevant Maps + Navigation SDKs enabled. Backend Routes credentials remain server-side (`TZ_GOOGLE_ROUTES_API_KEY`). Native Navigation keys are separate application credentials and must be restricted to the Android package/signing certificate or iOS bundle identifier as applicable; values must not be committed.

Native prerequisites still missing from this repository/environment: Android Studio/SDK + signing setup, Xcode 26.x + iOS signing/provisioning, bundle/package identifiers confirmed for production, device-specific API-key restrictions, a named physical Android test phone, and a named physical iPhone. The current repository also contains no native permission manifests to review.

The native plugin contract for B must provide capability, start, stop, state, and callback forwarding for progress/reroute/arrival/failure. At start, it must recalculate from the phone's actual current location even if planning used a manual address. Continuous location begins only after explicit Start Navigation, OS permission, and required provider consent. Arrival, cancellation, logout, permission revocation, and terminal failure must stop app-requested location subscriptions/listeners and invoke documented SDK cleanup. Screen navigation alone is not cleanup.

Provider UI/policy constraints must remain inside the native guidance view: preserve Google attribution and critical navigation UI, avoid promotional overlays or distracting content, present required terms/disclosures, and use supported background/location indicators. If background or lock-screen continuation is unavailable on a target configuration, THREEZONE must report the interruption rather than implying continued guidance.

Navigation SDK billing must be monitored independently from the server Routes API. Google documents Navigation SDK charging around destination requests; starting guidance itself is not the only cost consideration. Quotas/budgets and route/destination request counters should be configured before production.

## State-machine contract for B

The required states are: `needs_origin`, `locating`, `calculating_route`, `route_ready`, `estimate_stale`, `starting_navigation`, `navigating`, `rerouting`, `interrupted`, `arrived`, `cancelled`, `unavailable_or_failed`, and `permission_denied`.

Allowed high-level transitions: `needs_origin -> locating|calculating_route`; `locating -> calculating_route|permission_denied|unavailable_or_failed`; `calculating_route -> route_ready|unavailable_or_failed`; `route_ready -> calculating_route|estimate_stale|starting_navigation`; `estimate_stale -> calculating_route`; `starting_navigation -> navigating|permission_denied|unavailable_or_failed`; `navigating -> rerouting|interrupted|arrived|cancelled|unavailable_or_failed`; `rerouting -> navigating|interrupted|cancelled|unavailable_or_failed`; `interrupted -> navigating|cancelled|unavailable_or_failed`. Terminal `arrived` and `cancelled` do not transition into each other. Repeated native callbacks must not manufacture repeated terminal outcomes.

## Gate to begin B

Milestone B starts only after milestone A fixture tests pass and a live Google Routes credential/configuration check succeeds in an authorized environment. B cannot pass until the embedded Google Navigation SDK is built into a real native shell and exercised on a named physical device. A web map, external Maps handoff, route animation, or simulator-only run does not satisfy the gate.

Physical-device evidence must record build SHA, device model, OS version, platform, test date, whether the run is simulated or real-location, guidance activation, ETA/distance updates, reroute observation, SDK arrival, cancellation/cleanup, permission changes, and regression of existing member-only backend behavior. Android and iOS require separate evidence before claiming support for both.
