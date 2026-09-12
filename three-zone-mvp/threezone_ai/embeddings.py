"""In-memory search index — vectors obtained only via AI Gateway."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from threezone_ai.gateway import run
from threezone_ai.types import AIRequest, CostCeiling, PrivacyClass, TaskType


@dataclass
class SearchHit:
    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Entry:
    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _embed_via_gateway(
    text: str,
    *,
    privacy_class: PrivacyClass | str = PrivacyClass.PUBLIC,
    cost_ceiling: CostCeiling | str = CostCeiling.FREE_ONLY,
) -> list[float] | None:
    resp = run(
        AIRequest(
            task_type=TaskType.EMBEDDING,
            input_text=text,
            privacy_class=privacy_class,
            cost_ceiling=cost_ceiling,
            require_human_review=False,
        ),
        record_lineage=False,
    )
    if resp.ok and resp.embedding:
        return resp.embedding
    return None


def enabled() -> bool:
    """True if embedding providers can produce a vector (gateway)."""
    vec = _embed_via_gateway("ping")
    return vec is not None and len(vec) > 0


class EmbeddingIndex:
    """Cosine similarity index; embeddings come from gateway only."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def add(
        self,
        id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        vector: list[float] | None = None,
    ) -> bool:
        """Add text. Returns False if gateway embedding fails — does not crash."""
        meta = dict(metadata or {})
        vec = vector if vector is not None else _embed_via_gateway(text)
        if vec is None:
            return False
        self._entries[id] = _Entry(id=id, text=text, vector=vec, metadata=meta)
        return True

    def search(
        self,
        query: str,
        k: int = 5,
        query_vector: list[float] | None = None,
    ) -> list[SearchHit]:
        if k < 1:
            return []
        qvec = query_vector if query_vector is not None else _embed_via_gateway(query)
        if qvec is None or not self._entries:
            return []
        scored = [
            SearchHit(
                id=e.id,
                score=_cosine(qvec, e.vector),
                text=e.text,
                metadata=dict(e.metadata),
            )
            for e in self._entries.values()
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


_default_index = EmbeddingIndex()


def get_index() -> EmbeddingIndex:
    return _default_index


def add(id: str, text: str, metadata: dict[str, Any] | None = None) -> bool:
    return _default_index.add(id, text, metadata)


def search(query: str, k: int = 5) -> list[SearchHit]:
    return _default_index.search(query, k=k)
