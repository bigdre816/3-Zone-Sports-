"""Canonical City/navigation signal vocabulary and evidence definitions.

Milestone A defines names and evidence only. It does not ingest native navigation
telemetry. Milestone C must use these canonical names and normalize any legacy
aliases before counting so one observation cannot be counted twice.
"""
from __future__ import annotations

CANONICAL_SIGNALS: dict[str, str] = {
    "city.place_impression": "The canonical place met the documented visibility rule.",
    "city.place_opened": "The member opened the canonical place detail.",
    "city.place_saved": "A save of the canonical place succeeded.",
    "directions_requested": "The member explicitly requested directions or an external navigation handoff.",
    "navigation.route_ready": "The navigation provider returned a usable route.",
    "navigation.started": "The embedded native integration confirmed active guidance; a button tap is insufficient.",
    "navigation.progress": "A valid SDK progress callback met the documented sparse reporting rule; elapsed time alone is insufficient.",
    "navigation.rerouted": "The native SDK reported a route change during the navigation session.",
    "navigation.cancelled": "The member explicitly ended the navigation session.",
    "navigation.arrived": "The native SDK reported arrival at the selected destination.",
    "navigation.failed": "A documented failure ended or prevented native navigation.",
    "offer.redeemed": "A separate authorized redemption mechanism verified the redemption.",
}

# Legacy aliases belong here only when one is discovered in the repository or
# migration record. Empty at milestone A: never invent aliases merely to fill it.
LEGACY_SIGNAL_ALIASES: dict[str, str] = {}

ARRIVAL_LIMITATION = (
    "An SDK arrival is a device-reported navigation outcome. It does not establish "
    "venue entry, event attendance, a purchase, or independently verified physical presence."
)


def canonical_signal_name(name: str) -> str:
    value = str(name or "").strip()
    return LEGACY_SIGNAL_ALIASES.get(value, value)
