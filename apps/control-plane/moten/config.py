"""Runtime configuration.

Phase 1 defaults to SQLite for a zero-infra, fully testable dev store. The
persistence layer is DB-agnostic (SQLAlchemy), so PostgreSQL — the recommended
production target per the spec — is a connection-string swap via MOTEN_DB_URL.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent.parent.parent


def database_url() -> str:
    url = os.environ.get("MOTEN_DB_URL")
    if url:
        return url
    db_path = os.environ.get("MOTEN_DB_PATH", str(APP_ROOT.parent / "moten.db"))
    return f"sqlite:///{db_path}"


# Central clock source label recorded on every event (spec §03 envelope).
CLOCK_SOURCE = os.environ.get("MOTEN_CLOCK_SOURCE", "trusted-time-service")
