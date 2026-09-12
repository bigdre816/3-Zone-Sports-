"""THREEZONE Vision Ontology v0 — brand-neutral class vocabulary.

Provider labels are mapped into THREEZONE classes. Mapping status is one of:
- supported: provider is allowed to emit this ontology class
- unsupported: known ontology class the provider does not cover (never invent)
- unknown: raw label has no mapping (do not fabricate a class)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

ONTOLOGY_VERSION = "threezone.vision.ontology.v0"

ONTOLOGY_CLASSES: frozenset[str] = frozenset(
    {
        "court",
        "field",
        "hoop",
        "basketball",
        "football_field",
        "goalpost",
        "soccer_goal",
        "volleyball_net",
        "wrestling_mat",
        "scoreboard",
        "referee",
        "team_bench",
        "uniformed_participant",
        "person",
        "tv_monitor_boundary",
    }
)

# Raw-label aliases → ontology class. Not a claim that any pretrained
# detector already covers these classes.
_ALIASES: dict[str, str] = {
    "basket": "hoop",
    "basketball_hoop": "hoop",
    "rim": "hoop",
    "backboard": "hoop",
    "hardwood": "court",
    "basketball_court": "court",
    "soccer_field": "field",
    "pitch": "field",
    "playing_field": "field",
    "american_football_field": "football_field",
    "goal_post": "goalpost",
    "goalposts": "goalpost",
    "goal": "soccer_goal",
    "football_goal": "soccer_goal",
    "net": "volleyball_net",
    "mat": "wrestling_mat",
    "score_board": "scoreboard",
    "ref": "referee",
    "bench": "team_bench",
    "player": "uniformed_participant",
    "athlete": "uniformed_participant",
    "human": "person",
    "people": "person",
    "tv": "tv_monitor_boundary",
    "television": "tv_monitor_boundary",
    "monitor": "tv_monitor_boundary",
    "screen": "tv_monitor_boundary",
}

SPORT_ANCHOR_CLASSES: dict[str, frozenset[str]] = {
    "basketball": frozenset({"court", "hoop", "basketball"}),
    "soccer": frozenset({"field", "soccer_goal"}),
    "football": frozenset({"field", "football_field", "goalpost"}),
    "volleyball": frozenset({"court", "volleyball_net"}),
    "wrestling": frozenset({"wrestling_mat"}),
}


class MappingStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OntologyMapping:
    raw_label: str
    ontology_class: str | None
    status: MappingStatus


def normalize_label(raw_label: str) -> str:
    return str(raw_label or "").strip().lower().replace(" ", "_").replace("-", "_")


def map_label(
    raw_label: str,
    provider_supported: Iterable[str] | None = None,
) -> OntologyMapping:
    """Map a provider raw label. Never invent a supported detection."""

    supported = {normalize_label(x) for x in (provider_supported or ())}
    raw = str(raw_label or "")
    key = normalize_label(raw)
    mapped = key if key in ONTOLOGY_CLASSES else _ALIASES.get(key)
    if mapped is None:
        return OntologyMapping(raw_label=raw, ontology_class=None, status=MappingStatus.UNKNOWN)
    if mapped in supported:
        return OntologyMapping(raw_label=raw, ontology_class=mapped, status=MappingStatus.SUPPORTED)
    return OntologyMapping(raw_label=raw, ontology_class=mapped, status=MappingStatus.UNSUPPORTED)


def provider_coverage(
    provider_supported: Iterable[str] | None = None,
) -> dict[str, str]:
    """Per-ontology-class coverage table for a provider."""

    supported = {normalize_label(x) for x in (provider_supported or ())}
    out: dict[str, str] = {}
    for cls in sorted(ONTOLOGY_CLASSES):
        out[cls] = (
            MappingStatus.SUPPORTED.value
            if cls in supported
            else MappingStatus.UNSUPPORTED.value
        )
    return out
