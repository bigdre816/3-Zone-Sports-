"""Sports vision evidence pipeline — observations only.

G3-B registers sports_vision on the AI gateway (kill-switch gated).
G3-C may resolve asset:archive:<id> via archive_lookup.
Does not fabricate provider versions (unknown if not observed).
Does not import ControlPlane.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from threezone_ai.vision.assets import (
    ResolvedAsset,
    SyntheticAssetResolver,
    resolve_authorized_asset,
)
from threezone_ai.vision.providers import (
    EscalationLayerResult,
    EscalationProvider,
    FakeEscalationProvider,
    FakeObjectDetectionProvider,
    FakeSceneReasoningProvider,
    ObjectDetectionProvider,
    SceneLayerResult,
    SceneReasoningProvider,
)
from threezone_ai.vision.sampler import EvidenceSampler, SampledFrame
from threezone_ai.vision.store import IsolatedEvidenceStore, idempotency_key
from threezone_ai.vision.types import (
    EVIDENCE_SCHEMA_VERSION,
    GATEWAY_TASK_VERSION,
    POLICY_VERSION,
    PROCESSING_POLICY_VERSION,
    EscalationObservation,
    SportsVisionEvidenceBundle,
)
from threezone_ai.vision.validate import (
    ValidationError,
    strip_poison_keys,
    validate_detections,
    validate_scene_payload,
)


class VisionPipelineDisabled(RuntimeError):
    """Flags off or environment not admitted — providers must not init/run."""


class PrivacyClassRejected(RuntimeError):
    """P3 / conflicting privacy — reject processing."""


def _pipeline_admitted(allow_offline_synthetic: bool) -> bool:
    if allow_offline_synthetic:
        return True
    try:
        from threezone_ai.config import process_ai_enabled

        return bool(process_ai_enabled())
    except Exception:
        return False


def run_evidence_pipeline(
    source_asset_id: str,
    *,
    resolver: SyntheticAssetResolver | None = None,
    archive_lookup=None,
    sampler: EvidenceSampler | None = None,
    detector: ObjectDetectionProvider | None = None,
    scene: SceneReasoningProvider | None = None,
    escalation: EscalationProvider | None = None,
    enable_escalation: bool = False,
    client_privacy_class: str | None = None,
    allow_offline_synthetic: bool = False,
    store: IsolatedEvidenceStore | None = None,
    clock: Callable[[], str] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> SportsVisionEvidenceBundle:
    """Resolve → sample → detect → reason → (optional fake escalate) → bundle.

    Providers are constructed only after admission. Default implementations
    are fakes. Real cloud SDKs are not imported.
    """

    if not _pipeline_admitted(allow_offline_synthetic):
        raise VisionPipelineDisabled(
            "AI flags off; sports-vision pipeline is not product-admitted"
        )

    if resolver is not None and archive_lookup is None:
        asset = resolver.resolve(
            source_asset_id, client_privacy_class=client_privacy_class
        )
    else:
        asset = resolve_authorized_asset(
            source_asset_id,
            client_privacy_class=client_privacy_class,
            archive_lookup=archive_lookup,
            synthetic_resolver=resolver,
        )
    if asset.environment not in {"isolated_test", "sandbox"}:
        raise VisionPipelineDisabled(
            f"environment {asset.environment!r} is not admitted for V0"
        )

    reason_codes: list[str] = []
    layer_errors: list[str] = []

    if client_privacy_class and str(client_privacy_class) != asset.input_privacy_class:
        reason_codes.append("ignored_client_privacy_spoof")

    if asset.input_privacy_class == "P3":
        layer_errors.append("privacy_p3_rejected")
        return _empty_bundle(
            asset,
            reason_codes=reason_codes + ["privacy_p3_rejected"],
            layer_errors=layer_errors,
            clock=clock,
            id_factory=id_factory,
        )

    sampler = sampler or EvidenceSampler()
    frames = sampler.sample(asset)
    if not frames:
        layer_errors.append("no_readable_frames")

    # Construct fakes only after admission + resolve.
    if detector is None:
        detector = FakeObjectDetectionProvider()
    if scene is None:
        scene = FakeSceneReasoningProvider()

    det_result = detector.detect(frames, asset)
    detector_version = _observed_version(getattr(det_result, "version", None))
    raw_det = getattr(det_result, "raw_payload", None)
    if isinstance(raw_det, dict):
        strip_poison_keys(raw_det, reason_codes)
    detections = []
    if getattr(det_result, "timed_out", False):
        layer_errors.append("detector_timeout")
    elif getattr(det_result, "error", None):
        layer_errors.append("detector_fail")
    else:
        try:
            detections = validate_detections(
                list(det_result.detections or []),
                provider_supported=getattr(detector, "supported_classes", None),
                allowed_frame_ids=frozenset(f.frame_id for f in frames),
                reason_codes=reason_codes,
            )
        except ValidationError as exc:
            layer_errors.append(exc.code)

    scene_result = scene.reason(
        frames, list(det_result.detections or []), asset
    )
    scene_version = _observed_version(getattr(scene_result, "version", None))
    scene_parsed: dict[str, Any]
    if getattr(scene_result, "timed_out", False):
        layer_errors.append("scene_timeout")
        scene_parsed = {
            "candidate_sports": [],
            "signals": [],
            "contradictions": [],
            "visibility_state": "unreadable",
            "unparseable": True,
        }
    elif getattr(scene_result, "error", None) and not getattr(scene_result, "unparseable", False):
        layer_errors.append("scene_fail")
        scene_parsed = {
            "candidate_sports": [],
            "signals": [],
            "contradictions": [],
            "visibility_state": asset.visibility_state,
            "unparseable": False,
        }
    else:
        try:
            scene_parsed = validate_scene_payload(
                scene_result.raw_payload
                if scene_result.raw_payload is not None
                else {
                    "candidate_sports": list(scene_result.candidate_sports or []),
                    "signals": list(scene_result.signals or []),
                    "contradictions": list(scene_result.contradictions or []),
                    "visibility_state": scene_result.visibility_state,
                },
                unparseable=bool(getattr(scene_result, "unparseable", False)),
                reason_codes=reason_codes,
            )
        except ValidationError as exc:
            layer_errors.append(exc.code)
            scene_parsed = {
                "candidate_sports": [],
                "signals": [],
                "contradictions": [],
                "visibility_state": "unreadable",
                "unparseable": True,
            }

    visibility = str(scene_parsed.get("visibility_state") or asset.visibility_state or "clear")
    if asset.visibility_state in {"obstructed", "unreadable"}:
        visibility = asset.visibility_state
    if not frames or visibility == "unreadable":
        if "no_readable_frames" not in layer_errors:
            layer_errors.append("no_readable_frames")

    esc_obs: EscalationObservation | None = None
    if enable_escalation:
        if escalation is None:
            escalation = FakeEscalationProvider()
        is_cloud = bool(getattr(escalation, "is_cloud", False))
        if is_cloud:
            layer_errors.append("cloud_escalation_blocked")
            reason_codes.append("cloud_escalation_blocked")
        elif asset.input_privacy_class == "P2" and is_cloud:
            layer_errors.append("p2_local_only")
        else:
            esc_result = escalation.escalate(
                frames, asset, list(det_result.detections or []), scene_result
            )
            if isinstance(getattr(esc_result, "raw_payload", None), dict):
                strip_poison_keys(esc_result.raw_payload, reason_codes)
            if getattr(esc_result, "timed_out", False):
                layer_errors.append("escalation_timeout")
            else:
                esc_obs = EscalationObservation(
                    provider=str(esc_result.provider or "unknown"),
                    model=str(esc_result.model or "unknown"),
                    model_version=_observed_version(esc_result.version),
                    additional_signals=tuple(esc_result.additional_signals or ()),
                    additional_contradictions=tuple(
                        esc_result.additional_contradictions or ()
                    ),
                    notes=str(esc_result.notes or ""),
                )

    created_at = (clock or _utcnow)()
    exec_id = (id_factory or _new_id)()
    trace_id = exec_id
    bundle_id = _bundle_id(asset, frames, detections, scene_parsed, reason_codes, layer_errors)

    signals = tuple(scene_parsed.get("signals") or ())
    if esc_obs:
        signals = signals + esc_obs.additional_signals
    contradictions = tuple(scene_parsed.get("contradictions") or ())
    if esc_obs:
        contradictions = contradictions + esc_obs.additional_contradictions

    bundle = SportsVisionEvidenceBundle(
        bundle_id=bundle_id,
        schema_version=EVIDENCE_SCHEMA_VERSION,
        environment=asset.environment,
        source_asset_id=asset.source_asset_id,
        source_asset_hash=asset.source_asset_hash,
        observation_window_start=frames[0].timestamp_s if frames else 0.0,
        observation_window_end=frames[-1].timestamp_s if frames else 0.0,
        frame_ids=tuple(f.frame_id for f in frames),
        frame_hashes=tuple(f.content_hash for f in frames),
        frame_timestamps=tuple(f.timestamp_s for f in frames),
        detector_provider=str(getattr(det_result, "provider", None) or getattr(detector, "name", "unknown")),
        detector_model=str(getattr(det_result, "model", None) or getattr(detector, "model", "unknown")),
        detector_version=detector_version,
        detections=tuple(detections),
        scene_provider=str(getattr(scene_result, "provider", None) or getattr(scene, "name", "unknown")),
        scene_model=str(getattr(scene_result, "model", None) or getattr(scene, "model", "unknown")),
        scene_model_version=scene_version,
        candidate_sports=tuple(scene_parsed.get("candidate_sports") or ()),
        signals=signals,
        contradictions=contradictions,
        visibility_state=visibility,
        escalation=esc_obs,
        input_privacy_class=asset.input_privacy_class,
        processing_policy_version=PROCESSING_POLICY_VERSION,
        gateway_task_version=GATEWAY_TASK_VERSION,
        execution_id=exec_id,
        trace_id=trace_id,
        created_at=created_at,
        reason_codes=tuple(reason_codes),
        layer_errors=tuple(layer_errors),
    )

    if store is not None:
        key = idempotency_key(
            asset.source_asset_id,
            bundle.detector_model,
            POLICY_VERSION,
        )
        bundle = store.remember(key, asset.source_asset_hash, bundle)
    return bundle


def verify_frame_hashes(
    bundle: SportsVisionEvidenceBundle, frames: tuple[SampledFrame, ...]
) -> bool:
    expected = tuple(f.content_hash for f in frames)
    return bundle.frame_hashes == expected and bundle.frame_ids == tuple(
        f.frame_id for f in frames
    )


def _observed_version(raw: Any) -> str:
    if raw is None or str(raw).strip() == "":
        return "unknown"
    return str(raw)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _bundle_id(
    asset: ResolvedAsset,
    frames: tuple[SampledFrame, ...],
    detections: list[Any],
    scene_parsed: dict[str, Any],
    reason_codes: list[str],
    layer_errors: list[str],
) -> str:
    material = "|".join(
        (
            asset.source_asset_id,
            asset.source_asset_hash,
            ",".join(f.content_hash for f in frames),
            ",".join(reason_codes),
            ",".join(layer_errors),
            str(len(detections)),
            ",".join(scene_parsed.get("candidate_sports") or ()),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"evb_{digest}"


def _empty_bundle(
    asset: ResolvedAsset,
    *,
    reason_codes: list[str],
    layer_errors: list[str],
    clock: Callable[[], str] | None,
    id_factory: Callable[[], str] | None,
) -> SportsVisionEvidenceBundle:
    created_at = (clock or _utcnow)()
    exec_id = (id_factory or _new_id)()
    return SportsVisionEvidenceBundle(
        bundle_id=_bundle_id(asset, (), [], {}, reason_codes, layer_errors),
        schema_version=EVIDENCE_SCHEMA_VERSION,
        environment=asset.environment,
        source_asset_id=asset.source_asset_id,
        source_asset_hash=asset.source_asset_hash,
        observation_window_start=0.0,
        observation_window_end=0.0,
        frame_ids=(),
        frame_hashes=(),
        frame_timestamps=(),
        detector_provider="none",
        detector_model="none",
        detector_version="unknown",
        detections=(),
        scene_provider="none",
        scene_model="none",
        scene_model_version="unknown",
        candidate_sports=(),
        signals=(),
        contradictions=(),
        visibility_state="unreadable",
        escalation=None,
        input_privacy_class=asset.input_privacy_class,
        processing_policy_version=PROCESSING_POLICY_VERSION,
        gateway_task_version=GATEWAY_TASK_VERSION,
        execution_id=exec_id,
        trace_id=exec_id,
        created_at=created_at,
        reason_codes=tuple(reason_codes),
        layer_errors=tuple(layer_errors),
    )
