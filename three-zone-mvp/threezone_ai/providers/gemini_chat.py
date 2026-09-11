"""Google Gemini chat — gateway-only."""

from __future__ import annotations

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType


class GeminiChatProvider(BaseProvider):
    name = "gemini"
    supported_tasks = {TaskType.DESCRIPTION}
    cost_band = "any"
    is_local = False

    def available(self, settings) -> bool:
        return bool(settings.gemini_api_key)

    def run(self, request: AIRequest, settings) -> ProviderResult:
        import httpx

        prompt = (request.input_text or "").strip()
        if not prompt:
            raise ValueError("description requires input_text")
        system = (request.metadata or {}).get("system")

        model = settings.gemini_model
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        text_in = f"System: {system}\n\nUser: {prompt}" if system else prompt
        body = {"contents": [{"parts": [{"text": text_in}]}]}
        timeout = max(1.0, (request.timeout_ms or 60_000) / 1000.0)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url,
                headers={"Content-Type": "application/json"},
                params={"key": settings.gemini_api_key},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        candidates = data.get("candidates") or []
        text = ""
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            if parts:
                text = (parts[0].get("text") or "").strip()
        return ProviderResult(
            text=text,
            model=model,
            version="gemini",
            confidence=0.7,
        )
