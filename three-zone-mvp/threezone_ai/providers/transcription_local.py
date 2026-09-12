"""Y4 — gateway-internal local transcription provider.

Distinct from ``transcription_offline`` (pure fake): uses local-path semantics
and optionally faster-whisper when installed + media exists. CI/tests always
get deterministic segments without requiring Whisper. Never calls Groq/Gemini.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType

if TYPE_CHECKING:
    from threezone_ai.config import Settings

GATEWAY_TASK_VERSION = "transcription.local.v0"
SEGMENT_SCHEMA_VERSION = "threezone.transcription.segments.v0"


def _deterministic_segments(source_key: str) -> list[dict[str, Any]]:
    """Stable local-path segments for CI / no-Whisper environments."""
    tag = (source_key or "synthetic").rsplit(":", 1)[-1][:32] or "clip"
    return [
        {
            "start": 0.0,
            "end": 2.0,
            "text": f"[local] Opening for {tag}.",
            "speaker": "announcer",
        },
        {
            "start": 2.0,
            "end": 4.5,
            "text": "Local transcription path — deterministic segments.",
            "speaker": "announcer",
        },
        {
            "start": 4.5,
            "end": 6.0,
            "text": "Human review required before any Treasure release.",
            "speaker": None,
        },
    ]


def segments_payload(segments: list[dict[str, Any]], *, language: str = "en") -> dict[str, Any]:
    return {
        "schema_version": SEGMENT_SCHEMA_VERSION,
        "segments": segments,
        "language": language,
        "publish": False,
        "treasure_release": False,
    }


def _try_faster_whisper(
    asset_ref: str | None, language: str | None, settings: "Settings"
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Optional real local Whisper. Returns None if unavailable / no media."""
    if not asset_ref:
        return None
    path = Path(str(asset_ref))
    if not path.is_file():
        return None
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    model_name = getattr(settings, "local_whisper_model", None) or "base"
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(path), language=language, beam_size=1
    )
    segments: list[dict[str, Any]] = []
    for seg in segments_iter:
        segments.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text.strip(),
                "speaker": None,
            }
        )
    lang = getattr(info, "language", language) or "en"
    return segments, str(model_name), str(lang)


class TranscriptionLocalProvider(BaseProvider):
    """Local-first transcription (is_local=True). Prefer over pure offline fake."""

    name = "transcription_local"
    supported_tasks = {TaskType.TRANSCRIPTION}
    cost_band = "free"
    is_local = True

    def available(self, settings: "Settings") -> bool:
        # Always available: deterministic path when Whisper/media missing.
        return True

    def run(self, request: AIRequest, settings: "Settings") -> ProviderResult:
        source_key = (
            request.source_asset_id
            or request.asset_ref
            or (request.metadata or {}).get("source_asset_id")
            or "asset:synthetic:transcription-local-001"
        )
        whisper = _try_faster_whisper(
            request.asset_ref, request.language, settings
        )
        if whisper is not None:
            segments, model_name, language = whisper
            mode = "faster_whisper"
        else:
            segments = _deterministic_segments(str(source_key))
            model_name = "transcription-local-deterministic-v0"
            language = request.language or "en"
            mode = "deterministic"

        payload = segments_payload(segments, language=language)
        text = " ".join(
            str(s.get("text") or "").strip() for s in segments if s.get("text")
        ).strip()
        return ProviderResult(
            text=json.dumps(payload, sort_keys=True),
            segments=segments,
            model=model_name,
            version=GATEWAY_TASK_VERSION,
            confidence=0.85 if mode == "faster_whisper" else 0.9,
            metadata={
                "schema_version": SEGMENT_SCHEMA_VERSION,
                "source_asset_id": str(source_key),
                "segment_count": len(segments),
                "language": payload["language"],
                "publish": False,
                "treasure_release": False,
                "human_review_required": True,
                "local_path": True,
                "local_mode": mode,
                "is_local": True,
            },
        )
