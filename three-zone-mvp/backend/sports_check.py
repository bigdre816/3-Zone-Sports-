"""V0b — Operator sports-check (read-only).

Runs the V0 sports-vision library against synthetic or authorized archive
source_asset_id values. Does not enable THREEZONE_AI_ENABLED, publish,
touch rights/score/settlement, or invent Treasure Path A release.
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
