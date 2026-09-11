"""Local faster-whisper captions provider."""

from __future__ import annotations

from pathlib import Path

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType


class LocalFasterWhisperProvider(BaseProvider):
    name = "local_faster_whisper"
    supported_tasks = {TaskType.CAPTION}
    cost_band = "free"
    is_local = True

    def available(self, settings) -> bool:
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False

    def run(self, request: AIRequest, settings) -> ProviderResult:
        from faster_whisper import WhisperModel

        if not request.asset_ref:
            raise ValueError("caption requires asset_ref (media path)")
        path = Path(request.asset_ref)
        if not path.is_file():
            raise FileNotFoundError(f"media not found: {path}")

        model_name = getattr(settings, "local_whisper_model", "base") or "base"
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments_iter, info = model.transcribe(
            str(path), language=request.language, beam_size=1
        )
        segments = []
        parts = []
        for seg in segments_iter:
            parts.append(seg.text.strip())
            segments.append(
                {
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": seg.text.strip(),
                }
            )
        text = " ".join(parts).strip()
        lang = getattr(info, "language", request.language)
        return ProviderResult(
            text=text,
            segments=segments,
            model=model_name,
            version="faster-whisper",
            confidence=0.75,
            metadata={"language": lang},
        )
