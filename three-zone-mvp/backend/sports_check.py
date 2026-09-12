"""V0b / G4-C — Operator sports-check (read-only) + private-frame verify.

Runs the V0 sports-vision library against synthetic or authorized archive
source_asset_id values, or against private capture frames (G4-C) via an
offline-admitted pipeline (allow_offline_synthetic). Does not enable
THREEZONE_AI_ENABLED, publish, touch rights/score/settlement, or invent
Treasure Path A release. Private verify never flips LIVE_PUBLIC.
"""

from __future__ import annotations

from typing import Any

from .control_plane import ControlPlane, ValidationError


def list_synthetic_assets(cp: ControlPlane, operator: dict) -> dict[str, Any]:
    cp.require_operator(operator)
    from threezone_ai.vision.assets import SyntheticAssetResolver

    resolver = SyntheticAssetResolver.default()
    assets: list[dict[str, Any]] = list(resolver.list_catalog_summaries())
    try:
        rows = cp.db.query(
            "SELECT archive_id, title, status, kind FROM archive_objects "
            "WHERE status='ARCHIVED' ORDER BY archive_id"
        )
        for row in rows:
            assets.append(
                {
                    "source_asset_id": f"asset:archive:{row['archive_id']}",
                    "scenario": "archive",
                    "input_privacy_class": "P1",
                    "environment": "sandbox",
                    "visibility_state": "clear",
                    "title": row.get("title"),
                }
            )
    except Exception:
        pass
    return {
        "assets": assets,
        "publish": False,
        "lane": "operator_sports_check_v0b",
        "note": (
            "Synthetic + authorized archive ids only. "
            "Policy decision is not publication or Treasure release."
        ),
    }


def run_sports_check(cp: ControlPlane, operator: dict, body: dict | None) -> dict[str, Any]:
    cp.require_operator(operator)
    body = body or {}
    source_asset_id = body.get("source_asset_id")
    if not isinstance(source_asset_id, str) or not source_asset_id.strip():
        raise ValidationError("source_asset_id required", "source_asset_id_required")

    from threezone_ai.vision.archive_lookup import archive_lookup_from_db
    from threezone_ai.vision.assets import IllicitAssetReference, UnknownArchiveAsset
    from threezone_ai.vision.pipeline import VisionPipelineDisabled, run_evidence_pipeline
    from threezone_ai.vision.policy import evaluate_sports_context

    try:
        bundle = run_evidence_pipeline(
            source_asset_id.strip(),
            allow_offline_synthetic=True,
            archive_lookup=archive_lookup_from_db(cp.db),
        )
    except IllicitAssetReference as exc:
        raise ValidationError(str(exc), "illicit_asset_reference") from exc
    except UnknownArchiveAsset as exc:
        raise ValidationError(str(exc), "archive_not_authorized") from exc
    except VisionPipelineDisabled as exc:
        raise ValidationError(str(exc), "vision_pipeline_disabled") from exc

    policy = evaluate_sports_context(bundle)
    return {
        "lane": "operator_sports_check_v0b",
        "publish": False,
        "treasure_release": False,
        "ai_gateway_enabled": False,
        "allow_offline_synthetic": True,
        "source_asset_id": bundle.source_asset_id,
        "bundle": bundle.to_canonical_dict(),
        "policy": policy.to_canonical_dict(),
        "note": (
            "Read-only operator view of SportsVisionEvidenceBundle + "
            "SportsContextPolicyResult. Not rights, lease, settlement, "
            "or Treasure Path A release."
        ),
    }



# ---------------------------------------------------------------------------
# G4-C — private capture frame sports-verify (evidence / policy only)
# ---------------------------------------------------------------------------

PRIVATE_SPORTS_CHECK_LANE = "private_capture_sports_check_g4c"
PRIVATE_SPORTS_CHECK_LABEL = (
    "Private sports-check — evidence/policy only — not publish authorization"
)


class _PrivateCaptureAssetResolver:
    """Resolve a single private ingest/rewind asset for offline evidence only.

    Never opens client-supplied paths/URLs. Frame descriptors are derived from
    authorized session metadata + content hash (same pattern as archive resolver).
    Scenario is honest ``private_capture`` — fake detectors yield empty/hold.
    """

    def __init__(
        self,
        *,
        live_session_id: str,
        private_asset_id: str,
        source_hash: str,
        byte_count: int | None = None,
    ) -> None:
        if not isinstance(private_asset_id, str) or not private_asset_id.startswith("priv_asset_"):
            raise ValidationError("invalid private asset id", "invalid_private_asset")
        if "/" in private_asset_id or "\\" in private_asset_id or ".." in private_asset_id:
            raise ValidationError("invalid private asset id", "invalid_private_asset")
        self.live_session_id = live_session_id
        self.private_asset_id = private_asset_id
        self.source_hash = source_hash
        self.byte_count = int(byte_count or 0)
        self.canonical_id = f"asset:private:{private_asset_id}"

    def resolve(self, source_asset_id: str, *, client_privacy_class: str | None = None):
        from threezone_ai.vision.assets import FrameDescriptor, IllicitAssetReference, ResolvedAsset

        ref = source_asset_id.strip() if isinstance(source_asset_id, str) else ""
        if ref != self.canonical_id:
            raise IllicitAssetReference("private asset id does not match session source")
        lowered = ref.lower()
        if lowered.startswith(("file://", "http://", "https://", "ftp://")):
            raise IllicitAssetReference("remote or file URL is not an asset id")
        frame_text = (
            f"private live capture frame session={self.live_session_id} "
            f"asset={self.private_asset_id} hash={self.source_hash[:16]}"
        )
        n = 10
        step = 20.0 / (n - 1)
        frames = tuple(
            FrameDescriptor(
                t=round(i * step, 6),
                text=frame_text,
                content_seed=f"{self.private_asset_id}:{i}:{self.source_hash[:12]}",
            )
            for i in range(n)
        )
        import hashlib
        import json

        hash_material = json.dumps(
            {
                "live_session_id": self.live_session_id,
                "private_asset_id": self.private_asset_id,
                "source_hash": self.source_hash,
                "byte_count": self.byte_count,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        asset_hash = "sha256:" + hashlib.sha256(hash_material.encode()).hexdigest()
        _ = client_privacy_class
        return ResolvedAsset(
            source_asset_id=self.canonical_id,
            source_asset_hash=asset_hash,
            input_privacy_class="P1",
            environment="sandbox",
            duration_s=20.0,
            scenario="private_capture",
            visibility_state="clear",
            frame_descriptors=frames,
            sample_frame_count=n,
            catalog_privacy_class="P1",
        )


def sports_status_from_policy_decision(decision: str) -> str:
    """Map SportsContextPolicy decision → honest live_session sports_status.

    Never returns a publish-authorizing status. ELIGIBLE_FOR_RIGHTS_CHECK is
    evidence/policy vocabulary only — not LIVE_PUBLIC / distribution ENABLED.
    """
    from threezone_ai.vision.types import (
        DECISION_ELIGIBLE,
        DECISION_HOLD,
        DECISION_REJECT,
    )

    if decision == DECISION_ELIGIBLE:
        return "ELIGIBLE_FOR_RIGHTS_CHECK"
    if decision == DECISION_HOLD:
        return "HOLD"
    if decision == DECISION_REJECT:
        return "REJECT_NON_SPORTS"
    return "UNVERIFIED"


def run_private_capture_sports_check(
    cp: ControlPlane,
    operator: dict,
    *,
    live_session_id: str,
    private_asset_id: str,
    source_hash: str,
    byte_count: int | None = None,
    offline_synthetic_asset_id: str | None = None,
) -> dict[str, Any]:
    """G4-C: run G3 evidence path on a private capture asset (or offline synthetic).

    Always returns publish=False. Does not enable prod AI gateway.
    ``offline_synthetic_asset_id`` (asset:synthetic:*) is optional operator
    dry-run admitted via allow_offline_synthetic; result still evidence-only.
    """
    cp.require_operator(operator)

    from threezone_ai.vision.assets import IllicitAssetReference, UnknownArchiveAsset
    from threezone_ai.vision.pipeline import VisionPipelineDisabled, run_evidence_pipeline
    from threezone_ai.vision.policy import evaluate_sports_context

    source_mode = "private_capture"
    try:
        if offline_synthetic_asset_id:
            # Optional offline synthetic dry-run — still not publish.
            from threezone_ai.vision.archive_lookup import archive_lookup_from_db

            sid = offline_synthetic_asset_id.strip()
            if not sid.startswith("asset:synthetic:"):
                raise ValidationError(
                    "offline_synthetic_asset_id must be asset:synthetic:<id>",
                    "invalid_offline_synthetic",
                )
            bundle = run_evidence_pipeline(
                sid,
                allow_offline_synthetic=True,
                archive_lookup=archive_lookup_from_db(cp.db),
            )
            source_mode = "offline_synthetic"
            used_source = sid
        else:
            resolver = _PrivateCaptureAssetResolver(
                live_session_id=live_session_id,
                private_asset_id=private_asset_id,
                source_hash=source_hash,
                byte_count=byte_count,
            )
            bundle = run_evidence_pipeline(
                resolver.canonical_id,
                resolver=resolver,
                archive_lookup=None,
                allow_offline_synthetic=True,
            )
            used_source = resolver.canonical_id
    except IllicitAssetReference as exc:
        raise ValidationError(str(exc), "illicit_asset_reference") from exc
    except UnknownArchiveAsset as exc:
        raise ValidationError(str(exc), "archive_not_authorized") from exc
    except VisionPipelineDisabled as exc:
        raise ValidationError(str(exc), "vision_pipeline_disabled") from exc

    policy = evaluate_sports_context(bundle)
    sports_status = sports_status_from_policy_decision(policy.decision)
    return {
        "lane": PRIVATE_SPORTS_CHECK_LANE,
        "label": PRIVATE_SPORTS_CHECK_LABEL,
        "publish": False,
        "treasure_release": False,
        "ai_gateway_enabled": False,
        "allow_offline_synthetic": True,
        "source_mode": source_mode,
        "live_session_id": live_session_id,
        "private_asset_id": private_asset_id,
        "source_asset_id": used_source,
        "source_hash": source_hash,
        "bundle_id": bundle.bundle_id,
        "decision": policy.decision,
        "sports_status": sports_status,
        "bundle": bundle.to_canonical_dict(),
        "policy": policy.to_canonical_dict(),
        "public_state": "LIVE_PRIVATE",
        "distribution_state": "DISABLED",
        "note": (
            "Private-frame sports-verify is evidence/policy only. "
            "Decision is NOT publication, LIVE_PUBLIC, distribution ENABLED, "
            "rights, lease, settlement, or Treasure Path A release."
        ),
    }
