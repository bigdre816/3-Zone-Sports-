"""Y2 — typed transcription offline/fake provider (gateway-internal).

Returns structured segments with a stable JSON schema. No Whisper/cloud SDKs;
real local path + immutable proposal belong to Y4.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType

if TYPE_CHECKING:
    from threezone_ai.config import Settings

GATEWAY_TASK_VERSION = "transcription.gateway.v0"
SEGMENT_SCHEMA_VERSION = "threezone.transcription.segments.v0"


def _stable_segments(source_key: str) -> list[dict[str, Any]]:
    """Deterministic fake segments for tests / offline demos."""
    # Fixed shape; text varies slightly with source so lineage is distinguishable.
    tag = (source_key or "synthetic").rsplit(":", 1)[-1][:32] or "clip"
    return [
        {
            "start": 0.0,
            "end": 2.5,
            "text": f"Welcome to the {tag} broadcast.",
            "speaker": "announcer",
        },
        {
            "start": 2.5,
            "end": 5.0,
            "text": "Play begins at midfield.",
            "speaker": "announcer",
        },
        {
            "start": 5.0,
            "end": 7.25,
            "text": "Crowd reacts to the possession change.",
            "speaker": None,
        },
    ]


def segments_payload(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Canonical typed-transcription payload (stable keys)."""
    return {
        "schema_version": SEGMENT_SCHEMA_VERSION,
        "segments": segments,
        "language": "en",
        "publish": False,
        "treasure_release": False,
    }


class TranscriptionOfflineProvider(BaseProvider):
    name = "transcription_offline"
    supported_tasks = {TaskType.TRANSCRIPTION}
    cost_band = "free"
    is_local = True

    def available(self, settings: "Settings") -> bool:
        return True

    def run(self, request: AIRequest, settings: "Settings") -> ProviderResult:
        source_key = (
            request.source_asset_id
            or request.asset_ref
            or (request.metadata or {}).get("source_asset_id")
            or "asset:synthetic:transcription-001"
        )
        segments = _stable_segments(str(source_key))
        payload = segments_payload(segments)
        text = " ".join(
            str(s.get("text") or "").strip() for s in segments if s.get("text")
        ).strip()
        return ProviderResult(
            text=json.dumps(payload, sort_keys=True),
            segments=segments,
            model="transcription-fake-v0",
            version=GATEWAY_TASK_VERSION,
            confidence=0.9,
            metadata={
                "schema_version": SEGMENT_SCHEMA_VERSION,
                "source_asset_id": str(source_key),
                "segment_count": len(segments),
                "language": payload["language"],
                "publish": False,
                "human_review_required": True,
            },
        )
