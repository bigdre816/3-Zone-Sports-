"""Deprecated shim — use threezone_ai.gateway.run(AIRequest) instead.

Kept so older sketches that imported complete() still resolve to the gateway.
"""

from __future__ import annotations

from dataclasses import dataclass

from threezone_ai.gateway import run
from threezone_ai.types import AIRequest, TaskType


@dataclass
class RouterResult:
    text: str
    provider: str
    model: str | None = None
    error: str | None = None


def complete(prompt: str, system: str | None = None) -> RouterResult:
    """Thin wrapper around gateway description task."""
    resp = run(
        AIRequest(
            task_type=TaskType.DESCRIPTION,
            input_text=prompt,
            metadata={"system": system} if system else {},
            require_human_review=False,
        )
    )
    provider = resp.provider if resp.ok else "no_provider"
    if resp.degraded:
        provider = "no_provider"
    return RouterResult(
        text=resp.text or "",
        provider=provider,
        model=resp.model,
        error=resp.error,
    )
