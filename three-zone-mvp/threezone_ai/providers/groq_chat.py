"""Groq chat — gateway-only."""

from __future__ import annotations

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType


class GroqChatProvider(BaseProvider):
    name = "groq"
    supported_tasks = {TaskType.DESCRIPTION}
    cost_band = "low"
    is_local = False

    def available(self, settings) -> bool:
        return bool(settings.groq_api_key)

    def run(self, request: AIRequest, settings) -> ProviderResult:
        import httpx

        prompt = (request.input_text or "").strip()
        if not prompt:
            raise ValueError("description requires input_text")
        system = (request.metadata or {}).get("system")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": settings.groq_chat_model,
            "messages": messages,
            "temperature": 0.4,
        }
        timeout = max(1.0, (request.timeout_ms or 60_000) / 1000.0)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        return ProviderResult(
            text=text,
            model=settings.groq_chat_model,
            version="groq-chat",
            confidence=0.75,
        )
