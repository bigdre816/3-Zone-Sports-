"""Cloudflare Workers AI chat — gateway-only."""

from __future__ import annotations

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType


class CloudflareChatProvider(BaseProvider):
    name = "cloudflare"
    supported_tasks = {TaskType.DESCRIPTION}
    cost_band = "any"
    is_local = False

    def available(self, settings) -> bool:
        return bool(settings.cloudflare_account_id and settings.cloudflare_api_token)

    def run(self, request: AIRequest, settings) -> ProviderResult:
        import httpx

        prompt = (request.input_text or "").strip()
        if not prompt:
            raise ValueError("description requires input_text")
        system = (request.metadata or {}).get("system")

        account = settings.cloudflare_account_id
        model = settings.cloudflare_model
        url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
        headers = {
            "Authorization": f"Bearer {settings.cloudflare_api_token}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": str(system)})
        messages.append({"role": "user", "content": prompt})
        timeout = max(1.0, (request.timeout_ms or 60_000) / 1000.0)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json={"messages": messages})
            resp.raise_for_status()
            data = resp.json()
        result = data.get("result") or {}
        text = result.get("response") or result.get("text") or ""
        if isinstance(text, dict):
            text = text.get("response") or text.get("text") or ""
        return ProviderResult(
            text=str(text).strip(),
            model=model,
            version="cloudflare-workers-ai",
            confidence=0.65,
        )
