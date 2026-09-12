"""Ollama nomic-embed-text — gateway-only."""

from __future__ import annotations

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType


class OllamaEmbedProvider(BaseProvider):
    name = "ollama_nomic"
    supported_tasks = {TaskType.EMBEDDING}
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

        text = (request.input_text or "").strip()
        if not text:
            raise ValueError("embedding requires input_text")

        base = settings.ollama_base_url.rstrip("/")
        model = settings.ollama_embed_model
        timeout = max(1.0, min(settings.ollama_timeout_s, (request.timeout_ms or 30_000) / 1000.0))
        payloads = [
            (f"{base}/api/embeddings", {"model": model, "prompt": text}),
            (f"{base}/api/embed", {"model": model, "input": text}),
        ]
        last_err: Exception | None = None
        with httpx.Client(timeout=timeout) as client:
            for url, body in payloads:
                try:
                    resp = client.post(url, json=body)
                    if resp.status_code >= 400:
                        continue
                    data = resp.json()
                    if isinstance(data.get("embedding"), list):
                        vec = [float(x) for x in data["embedding"]]
                        return ProviderResult(
                            embedding=vec,
                            model=model,
                            version="ollama-embed",
                            confidence=1.0,
                        )
                    emb = data.get("embeddings")
                    if isinstance(emb, list) and emb and isinstance(emb[0], list):
                        return ProviderResult(
                            embedding=[float(x) for x in emb[0]],
                            model=model,
                            version="ollama-embed",
                            confidence=1.0,
                        )
                except Exception as exc:
                    last_err = exc
                    continue
        raise RuntimeError(f"ollama embed failed: {last_err}")
