"""Captions feature helpers — call the AI Gateway only (no provider SDKs)."""

from __future__ import annotations

from pathlib import Path

from threezone_ai.gateway import run
from threezone_ai.types import AIRequest, AIResponse, CostCeiling, PrivacyClass, TaskType


class CaptionError(RuntimeError):
    """Raised when a strict helper wants an exception instead of degraded response."""


def transcribe(
    path: str | Path,
    language: str | None = None,
    *,
    privacy_class: PrivacyClass | str = PrivacyClass.PUBLIC,
    cost_ceiling: CostCeiling | str = CostCeiling.ANY,
    source_asset_id: str | None = None,
    require_human_review: bool | None = None,
    raise_on_no_ai: bool = True,
) -> AIResponse:
    """
    Transcribe media via gateway.run(task_type=caption).

    Product code should prefer gateway.run(AIRequest(...)) directly.
    """
    p = Path(path)
    if not p.is_file():
        raise CaptionError(f"Audio/video file not found: {p}")

    resp = run(
        AIRequest(
            task_type=TaskType.CAPTION,
            asset_ref=str(p),
            language=language,
            privacy_class=privacy_class,
            cost_ceiling=cost_ceiling,
            source_asset_id=source_asset_id or str(p),
            require_human_review=require_human_review,
            metadata={"skip_title": False},
        )
    )
    if raise_on_no_ai and (not resp.ok or resp.provider == "no_ai"):
        raise CaptionError(resp.error or "caption failed (no_ai)")
    return resp


def suggest_title(
    transcript: str,
    *,
    privacy_class: PrivacyClass | str = PrivacyClass.PUBLIC,
    cost_ceiling: CostCeiling | str = CostCeiling.ANY,
) -> str:
    """Title suggestion via gateway description task."""
    text = (transcript or "").strip()
    if not text:
        return "Untitled clip"
    resp = run(
        AIRequest(
            task_type=TaskType.DESCRIPTION,
            input_text=(
                "Suggest a short catchy sports highlight title (max 8 words). "
                "Reply with the title only.\n\n"
                f"{text[:2000]}"
            ),
            privacy_class=privacy_class,
            cost_ceiling=cost_ceiling,
            metadata={"system": "You write concise sports highlight titles."},
            require_human_review=False,
        ),
        record_lineage=False,
    )
    if resp.ok and resp.text:
        return resp.text.strip().splitlines()[0].strip().strip("\"'")[:120]
    words = text.split()
    snippet = " ".join(words[:8])
    if len(words) > 8:
        snippet += "…"
    return snippet[:80] or "Untitled clip"
