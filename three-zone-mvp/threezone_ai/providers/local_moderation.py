"""Local moderation stub (keyword heuristic) — gateway-only."""

from __future__ import annotations

from threezone_ai.providers.base import BaseProvider
from threezone_ai.types import AIRequest, ProviderResult, TaskType

_BLOCKLIST = {
    "slur-example-block",  # placeholder tokens for tests / demo
}


class LocalModerationProvider(BaseProvider):
    name = "local_classifier_stub"
    supported_tasks = {TaskType.MODERATION}
    cost_band = "free"
    is_local = True

    def available(self, settings) -> bool:
        return True

    def run(self, request: AIRequest, settings) -> ProviderResult:
        text = (request.input_text or "").lower()
        flagged = [w for w in _BLOCKLIST if w in text]
        # Also flag empty as inconclusive
        safe = not flagged
        conf = 0.9 if flagged else 0.6
        return ProviderResult(
            text="flagged" if flagged else "allow",
            labels={
                "allow": safe,
                "flagged_terms": flagged,
                "action": "block" if flagged else "allow",
            },
            model="local_classifier_stub",
            version="0.1",
            confidence=conf,
        )
