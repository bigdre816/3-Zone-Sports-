"""Deterministic SportsContextPolicy v0.

THREEZONE-owned. Never imports ControlPlane. Never mutates rights, score,
lease, settlement, Moten, or Treasure. "eligible_for_rights_check" means a
later ticket *may* invoke an existing ControlPlane path — V0 does not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Iterable

from threezone_ai.vision.ontology import MappingStatus
from threezone_ai.vision.types import (
    DECISION_ELIGIBLE,
    DECISION_HOLD,
    DECISION_REJECT,
    POLICY_VERSION,
    Detection,
    SportsContextPolicyResult,
    SportsVisionEvidenceBundle,
)

# Fail-closed layer errors that can never produce eligible.
_HOLD_ERRORS = frozenset(
    {
        "detector_timeout",
        "scene_timeout",
        "escalation_timeout",
        "scene_fail",
        "detector_fail",
        "scene_unparseable",
        "no_readable_frames",
        "privacy_p3_rejected",
        "nan_or_inf_score",
        "negative_confidence",
        "oob_bbox",
        "malformed_score",
        "malformed_bbox",
        "malformed_detections",
        "malformed_detection",
        "output_too_large",
        "unknown_frame_id",
        "frame_hash_mismatch",
        "source_asset_hash_mismatch",
        "cloud_escalation_blocked",
    }
)

_SPORT_EQUIPMENT = frozenset({"hoop", "basketball", "soccer_goal", "goalpost"})
_SPORT_VENUE = frozenset({"court", "field", "football_field", "wrestling_mat"})


def evaluate_sports_context(
    bundle: SportsVisionEvidenceBundle,
    *,
    source_asset_hash_checked: str | None = None,
    expected_frame_hashes: tuple[str, ...] | None = None,
    clock: Callable[[], str] | None = None,
) -> SportsContextPolicyResult:
    """Map an evidence bundle to eligible | hold | reject. Deterministic."""

    reasons: list[str] = []
    checked = (
        source_asset_hash_checked
        if source_asset_hash_checked is not None
        else bundle.source_asset_hash
    )
    if checked != bundle.source_asset_hash:
        reasons.append("source_asset_hash_mismatch")
    if expected_frame_hashes is not None and expected_frame_hashes != bundle.frame_hashes:
        reasons.append("frame_hash_mismatch")

    for err in bundle.layer_errors:
        if err in _HOLD_ERRORS or err.endswith("_timeout") or err.endswith("_fail"):
            reasons.append(err)

    if "scene_unparseable" in bundle.reason_codes:
        reasons.append("scene_unparseable")

    vis = bundle.visibility_state
    if vis == "unreadable" or not bundle.frame_ids:
        reasons.append("no_readable_frames")
    if vis == "obstructed":
        reasons.append("obstructed")

    supported = [d for d in bundle.detections if d.mapping_status == MappingStatus.SUPPORTED.value]
    unknown = [d for d in bundle.detections if d.mapping_status == MappingStatus.UNKNOWN.value]
    unsupported = [
        d for d in bundle.detections if d.mapping_status == MappingStatus.UNSUPPORTED.value
    ]
    classes = {d.ontology_class for d in supported if d.ontology_class}

    if "tv_monitor_boundary" in classes:
        reasons.append("tv_in_frame")

    if unknown and not classes.intersection(_SPORT_VENUE | _SPORT_EQUIPMENT):
        reasons.append("unknown_ontology_label")
    if unsupported and not classes.intersection(_SPORT_VENUE | _SPORT_EQUIPMENT):
        reasons.append("unsupported_ontology")

    emptyish = _empty_or_inactive(classes, supported)
    if emptyish:
        reasons.append("empty_or_inactive")

    # Fail-closed holds take priority — never eligible.
    blocking = [r for r in reasons if r in _HOLD_ERRORS or r in {
        "source_asset_hash_mismatch",
        "frame_hash_mismatch",
        "no_readable_frames",
        "obstructed",
        "tv_in_frame",
        "empty_or_inactive",
        "scene_unparseable",
        "unknown_ontology_label",
        "unsupported_ontology",
        "detector_timeout",
        "scene_timeout",
        "escalation_timeout",
        "scene_fail",
        "detector_fail",
    }]

    decision: str
    if blocking:
        decision = DECISION_HOLD
        if "privacy_p3_rejected" in reasons:
            decision = DECISION_HOLD
    elif _strong_sports(classes):
        decision = DECISION_ELIGIBLE
        reasons.append("sports_context_evidence_ok")
    elif _clear_non_sports(classes, bundle.signals, bundle.candidate_sports):
        decision = DECISION_REJECT
        reasons.append("non_sports_context")
    else:
        decision = DECISION_HOLD
        reasons.append("insufficient_sports_evidence")

    # Final invariant: any timeout / scene fail / hash mismatch cannot be eligible.
    if decision == DECISION_ELIGIBLE and any(
        r in reasons
        for r in (
            "scene_fail",
            "detector_timeout",
            "scene_timeout",
            "source_asset_hash_mismatch",
            "frame_hash_mismatch",
            "no_readable_frames",
            "tv_in_frame",
        )
    ):
        decision = DECISION_HOLD

    evaluated_at = clock() if clock else datetime.now(timezone.utc).isoformat()
    return SportsContextPolicyResult(
        evidence_bundle_id=bundle.bundle_id,
        policy_version=POLICY_VERSION,
        decision=decision,
        reason_codes=tuple(_dedupe(reasons)),
        evaluated_at=evaluated_at,
        source_asset_hash_checked=checked,
        evidence_content_hash=bundle.content_hash(),
    )


def _strong_sports(classes: set[str]) -> bool:
    basketball = (
        "hoop" in classes
        and ("court" in classes or "basketball" in classes)
        and ("uniformed_participant" in classes or "basketball" in classes)
    )
    soccer = "field" in classes and "soccer_goal" in classes and (
        "uniformed_participant" in classes or "person" in classes
    )
    football = (
        ("field" in classes or "football_field" in classes)
        and "goalpost" in classes
        and ("uniformed_participant" in classes or "person" in classes)
    )
    return bool(basketball or soccer or football)


def _empty_or_inactive(classes: set[str], detections: list[Detection]) -> bool:
    venue_only = bool(classes.intersection(_SPORT_VENUE)) and not classes.intersection(
        _SPORT_EQUIPMENT | {"uniformed_participant"}
    )
    return venue_only and not any(d.ontology_class in _SPORT_EQUIPMENT for d in detections)


def _clear_non_sports(
    classes: set[str], signals: Iterable[str], candidates: Iterable[str]
) -> bool:
    if classes.intersection(_SPORT_VENUE | _SPORT_EQUIPMENT):
        return False
    if any(candidates):
        return False
    blob = " ".join(signals).lower()
    non_sports_hints = ("office", "desk", "kitchen", "classroom", "hallway", "no court")
    return any(h in blob for h in non_sports_hints) or not classes.intersection(
        _SPORT_VENUE | _SPORT_EQUIPMENT
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
