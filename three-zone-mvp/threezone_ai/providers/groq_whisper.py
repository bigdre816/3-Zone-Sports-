"""Groq Whisper API — gateway-only."""

from __future__ import annotations

from pathlib import Path

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType


class GroqWhisperProvider(BaseProvider):
    name = "groq_whisper"
    supported_tasks = {TaskType.CAPTION}
    cost_band = "low"
    is_local = False

    def available(self, settings) -> bool:
        return bool(settings.groq_api_key)

    def run(self, request: AIRequest, settings) -> ProviderResult:
        import httpx

        if not request.asset_ref:
            raise ValueError("caption requires asset_ref (media path)")
        path = Path(request.asset_ref)
        if not path.is_file():
            raise FileNotFoundError(f"media not found: {path}")

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
        data = {
            "model": settings.groq_whisper_model,
            "response_format": "verbose_json",
        }
        if request.language:
            data["language"] = request.language

        timeout = max(1.0, (request.timeout_ms or 60_000) / 1000.0)
        with path.open("rb") as f:
            files = {"file": (path.name, f, "application/octet-stream")}
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, data=data, files=files)
                resp.raise_for_status()
                payload = resp.json()

        text = (payload.get("text") or "").strip()
        segments_raw = payload.get("segments") or []
        segments = [
            {
                "start": float(s.get("start", 0)),
                "end": float(s.get("end", 0)),
                "text": (s.get("text") or "").strip(),
            }
            for s in segments_raw
            if isinstance(s, dict)
        ]
        return ProviderResult(
            text=text,
            segments=segments,
            model=settings.groq_whisper_model,
            version="groq-whisper",
            confidence=0.8,
            metadata={"language": payload.get("language") or request.language},
        )
