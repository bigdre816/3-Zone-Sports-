"""Append-only generation lineage (JSONL scaffold; optional SQLite)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from threezone_ai.config import get_settings

_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "lin") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class LineageRecord:
    id: str
    event: str  # generation | human_edit | approval
    ts: str
    source_asset_id: str | None = None
    provider: str | None = None
    model: str | None = None
    version: str | None = None
    generated_output: str | None = None
    output_id: str | None = None
    human_edit: str | None = None
    editor: str | None = None
    approved_final: str | None = None
    approver: str | None = None
    task_type: str | None = None
    trace_id: str | None = None
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LineageStore:
    """Append-only provenance store."""

    def __init__(self, path: str | Path | None = None, backend: str | None = None) -> None:
        settings = get_settings()
        self.path = Path(path or settings.lineage_path)
        self.backend = (backend or settings.lineage_backend or "jsonl").lower()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "sqlite":
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lineage (
                    id TEXT PRIMARY KEY,
                    event TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def append(self, record: LineageRecord) -> LineageRecord:
        with _lock:
            if self.backend == "sqlite":
                with sqlite3.connect(self.path) as conn:
                    conn.execute(
                        "INSERT INTO lineage (id, event, ts, payload) VALUES (?, ?, ?, ?)",
                        (
                            record.id,
                            record.event,
                            record.ts,
                            json.dumps(record.to_dict(), ensure_ascii=False),
                        ),
                    )
                    conn.commit()
            else:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def iter_records(self) -> list[LineageRecord]:
        if not self.path.exists():
            return []
        rows: list[LineageRecord] = []
        if self.backend == "sqlite":
            with sqlite3.connect(self.path) as conn:
                cur = conn.execute("SELECT payload FROM lineage ORDER BY ts ASC, id ASC")
                for (payload,) in cur.fetchall():
                    rows.append(LineageRecord(**json.loads(payload)))
            return rows
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(LineageRecord(**json.loads(line)))
        return rows

    def get_lineage(self, asset_or_output_id: str) -> list[LineageRecord]:
        """Return ordered chain touching this asset or output id."""
        wanted = asset_or_output_id
        all_rows = self.iter_records()
        related = [
            r
            for r in all_rows
            if wanted
            in {
                r.id,
                r.source_asset_id,
                r.output_id,
                r.parent_id,
            }
            or (r.metadata or {}).get("asset_or_output_id") == wanted
        ]
        # Also follow parent links from matched generations
        ids = {r.id for r in related}
        changed = True
        while changed:
            changed = False
            for r in all_rows:
                if r.id in ids:
                    continue
                if r.parent_id in ids or r.output_id in {
                    x.output_id for x in related if x.output_id
                }:
                    related.append(r)
                    ids.add(r.id)
                    changed = True
        related.sort(key=lambda r: (r.ts, r.id))
        return related


_store: LineageStore | None = None


def get_store(path: str | Path | None = None, backend: str | None = None, reset: bool = False) -> LineageStore:
    global _store
    if _store is None or reset or path is not None:
        _store = LineageStore(path=path, backend=backend)
    return _store


def reset_store() -> None:
    global _store
    _store = None


def record_generation(
    *,
    source_asset_id: str | None,
    provider: str,
    model: str | None,
    version: str | None,
    generated_output: str | None,
    task_type: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    store: LineageStore | None = None,
) -> LineageRecord:
    st = store or get_store()
    output_id = _new_id("out")
    rec = LineageRecord(
        id=_new_id("gen"),
        event="generation",
        ts=_utc_now(),
        source_asset_id=source_asset_id,
        provider=provider,
        model=model,
        version=version,
        generated_output=generated_output,
        output_id=output_id,
        task_type=task_type,
        trace_id=trace_id,
        metadata=dict(metadata or {}),
    )
    return st.append(rec)


def record_human_edit(
    *,
    output_id: str,
    human_edit: str,
    editor: str | None = None,
    source_asset_id: str | None = None,
    parent_id: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    store: LineageStore | None = None,
) -> LineageRecord:
    st = store or get_store()
    rec = LineageRecord(
        id=_new_id("edit"),
        event="human_edit",
        ts=_utc_now(),
        source_asset_id=source_asset_id,
        output_id=output_id,
        human_edit=human_edit,
        editor=editor,
        parent_id=parent_id,
        trace_id=trace_id,
        metadata=dict(metadata or {}),
    )
    return st.append(rec)


def record_approval(
    *,
    output_id: str,
    approved_final: str,
    approver: str | None = None,
    source_asset_id: str | None = None,
    parent_id: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    store: LineageStore | None = None,
) -> LineageRecord:
    st = store or get_store()
    rec = LineageRecord(
        id=_new_id("apr"),
        event="approval",
        ts=_utc_now(),
        source_asset_id=source_asset_id,
        output_id=output_id,
        approved_final=approved_final,
        approver=approver,
        parent_id=parent_id,
        trace_id=trace_id,
        metadata=dict(metadata or {}),
    )
    return st.append(rec)


def get_lineage(asset_or_output_id: str, store: LineageStore | None = None) -> list[LineageRecord]:
    st = store or get_store()
    return st.get_lineage(asset_or_output_id)
