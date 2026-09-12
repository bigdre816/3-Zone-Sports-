"""Build authorized archive lookups for G3-C (no arbitrary path opens)."""

from __future__ import annotations

from typing import Any, Callable


def archive_lookup_from_db(db) -> Callable[[str], dict[str, Any] | None]:
    """Return lookup(archive_id) using archive_objects (+ optional team sport)."""

    def lookup(archive_id: str) -> dict[str, Any] | None:
        row = db.query_one(
            """
            SELECT a.*, t.sport AS sport, t.name AS team
            FROM archive_objects a
            LEFT JOIN teams t ON t.team_id = a.team_id
            WHERE a.archive_id = ?
            """,
            (archive_id,),
        )
        return dict(row) if row else None

    return lookup
