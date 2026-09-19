"""NavigationService — Milestone B capability stub.

Route planning (A) and native turn-by-turn (B) are separate services.
Until the Navigation SDK, Capacitor plugin, billing, and device signing
exist, native is false. This service must not emit navigation.started.
"""

from __future__ import annotations

MILESTONE_B_BLOCKERS = (
    "Google Navigation SDK for Android is not integrated in this repo",
    "Google Navigation SDK for iOS is not integrated in this repo",
    "Capacitor lives in the Lovable Member Gateway (separate); no plugin here",
    "Navigation SDK billing / Maps platform product enablement is unset",
    "App signing and store credentials for a physical-device build are unset",
    "No verified physical-device session exists",
)


class NavigationService:
    """Capability probe only. Does not start, stop, or simulate navigation."""

    milestone = "B"

    def capability(self) -> dict:
        return {
            "native": False,
            "turn_by_turn": False,
            "milestone": self.milestone,
            "status": "not_implemented",
            "reason": (
                "Native Navigation SDK is Milestone B. Milestone A is "
                "server-side Getting There planning only."
            ),
            "emits_navigation_started": False,
            "emits_navigation_arrived": False,
            "blockers": list(MILESTONE_B_BLOCKERS),
        }
