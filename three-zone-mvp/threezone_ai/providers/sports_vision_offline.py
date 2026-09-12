"""G3-B — local sports-vision evidence provider (gateway-internal).

Runs the V0 fake evidence pipeline + SportsContextPolicy. No cloud SDKs,
no YOLO brand lock-in, no arbitrary filesystem opens.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType

if TYPE_CHECKING:
    from threezone_ai.config import Settings


class SportsVisionOfflineProvider(BaseProvider):
    name = "sports_vision_offline"
    supported_tasks = {TaskType.SPORTS_VISION}
    cost_band = "free"
    is_local = True

    def available(self, settings: "Settings") -> bool:
        return True

    def run(self, request: AIRequest, settings: "Settings") -> ProviderResult:
        from threezone_ai.vision.pipeline import run_evidence_pipeline
        from threezone_ai.vision.policy import evaluate_sports_context

        source_asset_id = (
            request.source_asset_id
            or request.asset_ref
            or (request.metadata or {}).get("source_asset_id")
        )
        archive_lookup = (request.metadata or {}).get("archive_lookup")
        # Gateway path requires AI kill switch (already passed). Do not use
        # allow_offline_synthetic — that bypass is for V0b/tests/CLI only.
        bundle = run_evidence_pipeline(
            str(source_asset_id),
            allow_offline_synthetic=False,
            archive_lookup=archive_lookup,
            client_privacy_class=(request.metadata or {}).get("client_privacy_class"),
        )
        policy = evaluate_sports_context(bundle)
        payload = {
            "bundle": bundle.to_canonical_dict(),
            "policy": policy.to_canonical_dict(),
            "publish": False,
            "treasure_release": False,
        }
        return ProviderResult(
            text=json.dumps(payload, sort_keys=True),
            model="sports-vision-fake-v0",
            version="sports-vision.gateway.v0",
            confidence=None,
            metadata={
                "decision": policy.decision,
                "source_asset_id": bundle.source_asset_id,
                "bundle_id": bundle.bundle_id,
                "publish": False,
                "human_review_required": True,
            },
        )
