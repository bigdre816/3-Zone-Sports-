"""Ollama chat (description / titles) — gateway-only."""

from __future__ import annotations

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType


class OllamaChatProvider(BaseProvider):
    name = "ollama_chat"
    supported_tasks = {TaskType.DESCRIPTION}
    cost_band = "free"
    is_local = True

    def available(self, settings) -> bool:
        import httpx

        try:
            with httpx.Client(timeout=min(5.0, settings.ollama_timeout_s)) as client:
                r = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                return r.status_code < 500
        except Exception:
            return False

    def run(self, request: AIRequest, settings) -> ProviderResult:
        import httpx

        prompt = (request.input_text or "").strip()
        if not prompt:
            raise ValueError("description requires input_text")
        system = (request.metadata or {}).get("system")

        url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": settings.ollama_chat_model,
            "messages": messages,
            "stream": False,
        }
        timeout = max(1.0, min(settings.ollama_timeout_s, (request.timeout_ms or 30_000) / 1000.0))
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        msg = data.get("message") or {}
        text = (msg.get("content") or data.get("response") or "").strip()
        return ProviderResult(
            text=text,
            model=settings.ollama_chat_model,
            version="ollama-chat",
            confidence=0.7,
        )
