"""Immutable Sports Vision Evidence Bundle + Policy Result (V0).

Observation object ≠ policy result ≠ publication authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

EVIDENCE_SCHEMA_VERSION = "threezone.vision.evidence.v0"
POLICY_VERSION = "sports-context-policy.v0"
PROCESSING_POLICY_VERSION = "sports-vision-processing.v0"
# Honest: V0 is not registered as a gateway task.
GATEWAY_TASK_VERSION = "unregistered"

DECISION_ELIGIBLE = "eligible_for_rights_check"
DECISION_HOLD = "hold_uncertain"
DECISION_REJECT = "reject_non_sports"
POLICY_DECISIONS = frozenset({DECISION_ELIGIBLE, DECISION_HOLD, DECISION_REJECT})

VISIBILITY_STATES = frozenset({"clear", "partial", "obstructed", "unreadable"})


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no extra whitespace, UTF-8 safe."""

    return json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def content_hash(value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonicalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _canonicalize(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _canonicalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


@dataclass(frozen=True)
class BoundingBox:
    """Normalized axis-aligned box in [0, 1] image space (x, y, w, h)."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Detection:
    ontology_class: str
    bbox: BoundingBox
    score: float
    frame_id: str
    mapping_status: str
    raw_label: str = ""


@dataclass(frozen=True)
class EscalationObservation:
    """Additional observations only — never a decision or publish grant."""

    provider: str
    model: str
    model_version: str
    additional_signals: tuple[str, ...] = ()
    additional_contradictions: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class SportsVisionEvidenceBundle:
    """Immutable AI observation record. No publication authority."""

    bundle_id: str
    schema_version: str
    environment: str
    source_asset_id: str
    source_asset_hash: str
    observation_window_start: float
    observation_window_end: float
    frame_ids: tuple[str, ...]
    frame_hashes: tuple[str, ...]
    frame_timestamps: tuple[float, ...]
    detector_provider: str
    detector_model: str
    detector_version: str
    detections: tuple[Detection, ...]
    scene_provider: str
    scene_model: str
    scene_model_version: str
    candidate_sports: tuple[str, ...]
    signals: tuple[str, ...]
    contradictions: tuple[str, ...]
    visibility_state: str
    escalation: EscalationObservation | None
    input_privacy_class: str
    processing_policy_version: str
    gateway_task_version: str
    execution_id: str
    trace_id: str
    created_at: str
    reason_codes: tuple[str, ...] = ()
    layer_errors: tuple[str, ...] = ()

    def to_canonical_dict(self) -> dict[str, Any]:
        return _canonicalize(self)

    def canonical_json(self) -> str:
        return canonical_json(self)

    def content_hash(self) -> str:
        return content_hash(self)

    def observation_fingerprint(self) -> str:
        """Idempotency material: identity of observation, not wall-clock ids."""

        payload = {
            "source_asset_id": self.source_asset_id,
            "source_asset_hash": self.source_asset_hash,
            "frame_hashes": list(self.frame_hashes),
            "detector_provider": self.detector_provider,
            "detector_model": self.detector_model,
            "detector_version": self.detector_version,
            "detections": _canonicalize(self.detections),
            "scene_provider": self.scene_provider,
            "scene_model": self.scene_model,
            "scene_model_version": self.scene_model_version,
            "candidate_sports": list(self.candidate_sports),
            "signals": list(self.signals),
            "contradictions": list(self.contradictions),
            "visibility_state": self.visibility_state,
            "escalation": _canonicalize(self.escalation),
            "input_privacy_class": self.input_privacy_class,
            "reason_codes": list(self.reason_codes),
            "layer_errors": list(self.layer_errors),
        }
        return content_hash(payload)


@dataclass(frozen=True)
class SportsContextPolicyResult:
    """THREEZONE-owned decision. Stops before rights/lease/settlement."""

    evidence_bundle_id: str
    policy_version: str
    decision: str
    reason_codes: tuple[str, ...]
    evaluated_at: str
    source_asset_hash_checked: str
    evidence_content_hash: str = ""

    def to_canonical_dict(self) -> dict[str, Any]:
        return _canonicalize(self)

    def canonical_json(self) -> str:
        return canonical_json(self)

    def content_hash(self) -> str:
        return content_hash(self)


@dataclass(frozen=True)
class LayerError:
    layer: str
    code: str
    message: str = ""


# Re-export field helper so callers can copy with replacements.
def replace_bundle(bundle: SportsVisionEvidenceBundle, **changes: Any) -> SportsVisionEvidenceBundle:
    from dataclasses import replace

    return replace(bundle, **changes)
