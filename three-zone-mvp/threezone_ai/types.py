"""Shared request/response types for the AI Gateway switchboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    CAPTION = "caption"
    EMBEDDING = "embedding"
    MODERATION = "moderation"
    DESCRIPTION = "description"
    SPORTS_VISION = "sports_vision"
    TRANSCRIPTION = "transcription"


class PrivacyClass(str, Enum):
    PUBLIC = "public"
    MEMBER = "member"
    RESTRICTED = "restricted"
    INTERNAL = "internal"


class CostCeiling(str, Enum):
    FREE_ONLY = "free_only"
    LOW = "low"
    ANY = "any"


class FallbackTier(str, Enum):
    LOCAL_FIRST = "local_first"
    OVERFLOW = "overflow"
    FALLBACK = "fallback"
    NO_AI = "no_ai"


@dataclass
class AIRequest:
    """Product-facing gateway request. Feature code builds this — never calls providers."""

    task_type: TaskType | str
    input_text: str | None = None
    asset_ref: str | None = None  # path, URL, or asset id
    allowed_providers: list[str] | None = None
    timeout_ms: int = 60_000
    privacy_class: PrivacyClass | str = PrivacyClass.PUBLIC
    cost_ceiling: CostCeiling | str = CostCeiling.ANY
    fallback_order: list[str] | None = None
    require_human_review: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    source_asset_id: str | None = None
    language: str | None = None
    k: int | None = None  # for search-style consumers

    def normalized_task(self) -> TaskType:
        if isinstance(self.task_type, TaskType):
            return self.task_type
        return TaskType(str(self.task_type).lower())

    def normalized_privacy(self) -> PrivacyClass:
        if isinstance(self.privacy_class, PrivacyClass):
            return self.privacy_class
        return PrivacyClass(str(self.privacy_class).lower())

    def normalized_cost(self) -> CostCeiling:
        if isinstance(self.cost_ceiling, CostCeiling):
            return self.cost_ceiling
        return CostCeiling(str(self.cost_ceiling).lower())


@dataclass
class AIResponse:
    """Structured gateway response — including no_ai degraded mode."""

    ok: bool
    task_type: str
    provider: str
    text: str | None = None
    embedding: list[float] | None = None
    labels: dict[str, Any] | None = None
    segments: list[dict[str, Any]] | None = None
    model: str | None = None
    version: str | None = None
    confidence: float | None = None
    human_review_required: bool = False
    degraded: bool = False
    fallback_path: list[str] = field(default_factory=list)
    error: str | None = None
    lineage_id: str | None = None
    title_suggestion: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None

    @classmethod
    def no_ai(
        cls,
        task_type: str,
        error: str,
        fallback_path: list[str] | None = None,
        human_review_required: bool = False,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "AIResponse":
        return cls(
            ok=False,
            task_type=task_type,
            provider="no_ai",
            degraded=True,
            error=error,
            fallback_path=list(fallback_path or []),
            human_review_required=human_review_required,
            confidence=None,
            trace_id=trace_id,
            metadata=dict(metadata or {}),
        )


@dataclass
class ProviderResult:
    """Internal provider output (not product-facing)."""

    text: str | None = None
    embedding: list[float] | None = None
    labels: dict[str, Any] | None = None
    segments: list[dict[str, Any]] | None = None
    model: str | None = None
    version: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
