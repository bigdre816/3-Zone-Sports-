"""Validate provider outputs. Structured poison keys are stripped.

Poison applies to structured authority fields only — natural-language
signals such as "hardwood court visible" are kept.
"""

from __future__ import annotations

import math
from typing import Any

from threezone_ai.vision.ontology import MappingStatus, map_label
from threezone_ai.vision.types import BoundingBox, Detection

# Structured keys only. Do not blanket-filter these tokens in NL strings.
POISON_STRUCTURED_KEYS = frozenset(
    {
        "publish",
        "approved",
        "rights_valid",
        "live",
        "official",
        "settlement_amount",
        "sports_status",
        "verified",
        "eligible_for_rights_check",
        "hold_uncertain",
        "reject_non_sports",
    }
)

# Execution-shaped keys: record and drop; never invoke.
EXECUTION_KEYS = frozenset(
    {
        "tool_call",
        "tool_calls",
        "function_call",
        "function_calls",
        "instructions",
        "system_instruction",
        "execute",
        "os_system",
    }
)

MAX_DETECTIONS = 256
MAX_SIGNALS = 64
MAX_SIGNAL_LEN = 2000
MAX_PAYLOAD_BYTES = 64_000
REASON_IGNORED_AUTHORITY = "ignored_model_authority_field"
REASON_IGNORED_EXEC = "ignored_model_execution_field"
REASON_BOUNDED = "model_output_bounded"


class ValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def strip_poison_keys(obj: Any, reason_codes: list[str]) -> Any:
    """Recursively drop structured poison / execution keys. Keep NL strings."""

    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for key, value in obj.items():
            lk = str(key).strip().lower()
            if lk in POISON_STRUCTURED_KEYS:
                if REASON_IGNORED_AUTHORITY not in reason_codes:
                    reason_codes.append(REASON_IGNORED_AUTHORITY)
                continue
            if lk in EXECUTION_KEYS:
                if REASON_IGNORED_EXEC not in reason_codes:
                    reason_codes.append(REASON_IGNORED_EXEC)
                continue
            cleaned[key] = strip_poison_keys(value, reason_codes)
        return cleaned
    if isinstance(obj, list):
        return [strip_poison_keys(v, reason_codes) for v in obj]
    if isinstance(obj, tuple):
        return [strip_poison_keys(v, reason_codes) for v in obj]
    return obj


def _finite_nonneg_score(score: Any) -> float:
    try:
        value = float(score)
    except (TypeError, ValueError) as exc:
        raise ValidationError("malformed_score", "confidence is not a number") from exc
    if math.isnan(value) or math.isinf(value):
        raise ValidationError("nan_or_inf_score", "confidence is NaN or Inf")
    if value < 0:
        raise ValidationError("negative_confidence", "confidence is negative")
    if value > 1.0:
        raise ValidationError("malformed_score", "confidence exceeds 1.0")
    return value


def _box(raw: Any) -> BoundingBox:
    if not isinstance(raw, dict):
        raise ValidationError("malformed_bbox", "bbox must be an object")
    try:
        x = float(raw.get("x"))
        y = float(raw.get("y"))
        w = float(raw.get("w", raw.get("width")))
        h = float(raw.get("h", raw.get("height")))
    except (TypeError, ValueError) as exc:
        raise ValidationError("malformed_bbox", "bbox coordinates are not numbers") from exc
    for name, val in (("x", x), ("y", y), ("w", w), ("h", h)):
        if math.isnan(val) or math.isinf(val):
            raise ValidationError("nan_or_inf_bbox", f"bbox {name} is NaN or Inf")
    if w <= 0 or h <= 0:
        raise ValidationError("oob_bbox", "bbox width/height must be positive")
    if x < 0 or y < 0 or x + w > 1.0000001 or y + h > 1.0000001:
        raise ValidationError("oob_bbox", "bbox is outside normalized [0,1] image")
    return BoundingBox(x=x, y=y, w=w, h=h)


def validate_detections(
    raw_detections: Any,
    *,
    provider_supported: frozenset[str] | None = None,
    allowed_frame_ids: frozenset[str] | None = None,
    reason_codes: list[str] | None = None,
) -> list[Detection]:
    codes = reason_codes if reason_codes is not None else []
    if raw_detections is None:
        return []
    if not isinstance(raw_detections, list):
        raise ValidationError("malformed_detections", "detections must be a list")
    if len(raw_detections) > MAX_DETECTIONS:
        raise ValidationError("output_too_large", "too many detections")
    out: list[Detection] = []
    for item in raw_detections:
        if not isinstance(item, dict):
            raise ValidationError("malformed_detection", "detection must be an object")
        cleaned = strip_poison_keys(item, codes)
        raw_label = str(cleaned.get("raw_label") or cleaned.get("label") or cleaned.get("ontology_class") or "")
        mapping = map_label(raw_label, provider_supported)
        ontology_class = mapping.ontology_class or ""
        score = _finite_nonneg_score(cleaned.get("score", cleaned.get("confidence")))
        bbox = _box(cleaned.get("bbox") or cleaned.get("box"))
        frame_id = str(cleaned.get("frame_id") or "")
        if allowed_frame_ids is not None and frame_id not in allowed_frame_ids:
            raise ValidationError("unknown_frame_id", f"detection frame_id not sampled: {frame_id}")
        out.append(
            Detection(
                ontology_class=ontology_class,
                bbox=bbox,
                score=score,
                frame_id=frame_id,
                mapping_status=mapping.status.value,
                raw_label=raw_label,
            )
        )
    return out


def validate_scene_payload(
    raw_payload: Any,
    *,
    unparseable: bool = False,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    codes = reason_codes if reason_codes is not None else []
    if unparseable or isinstance(raw_payload, str):
        codes.append("scene_unparseable")
        return {
            "candidate_sports": [],
            "signals": [],
            "contradictions": [],
            "visibility_state": "unreadable",
            "unparseable": True,
        }
    if raw_payload is None:
        return {
            "candidate_sports": [],
            "signals": [],
            "contradictions": [],
            "visibility_state": "clear",
        }
    if not isinstance(raw_payload, dict):
        codes.append("scene_unparseable")
        return {
            "candidate_sports": [],
            "signals": [],
            "contradictions": [],
            "visibility_state": "unreadable",
            "unparseable": True,
        }
    size = _approx_size(raw_payload)
    if size > MAX_PAYLOAD_BYTES:
        raise ValidationError("output_too_large", "scene payload exceeds bound")
    cleaned = strip_poison_keys(raw_payload, codes)
    signals = _bound_strings(cleaned.get("signals") or [], codes)
    contradictions = _bound_strings(cleaned.get("contradictions") or [], codes)
    candidates = _bound_strings(cleaned.get("candidate_sports") or [], codes, maxlen=64)
    vis = str(cleaned.get("visibility_state") or "clear")
    return {
        "candidate_sports": candidates,
        "signals": signals,
        "contradictions": contradictions,
        "visibility_state": vis,
        "unparseable": False,
    }


def _bound_strings(values: Any, codes: list[str], maxlen: int = MAX_SIGNAL_LEN) -> list[str]:
    if not isinstance(values, list):
        return []
    if len(values) > MAX_SIGNALS:
        raise ValidationError("output_too_large", "too many signals")
    out: list[str] = []
    for item in values:
        text = str(item)
        if len(text) > maxlen:
            raise ValidationError("output_too_large", "signal exceeds length bound")
        out.append(text)
    return out


def _approx_size(obj: Any) -> int:
    try:
        import json

        return len(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return MAX_PAYLOAD_BYTES + 1
