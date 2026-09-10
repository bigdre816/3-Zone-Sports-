"""Database engine, session, and the immutable-version enforcement layer.

The immutability invariant (AGENTS.md §2.2 "Version history never disappears")
is enforced at TWO layers:

1. Service layer: version rows are only ever inserted; the sole permitted
   mutation is a controlled status transition via ``versioning.supersede``.
2. Database layer: generated triggers reject DELETE on any version row and
   reject UPDATE of any immutable column (only ``status`` and ``change_reason``
   may change). Triggers are emitted for SQLite (dev) and PostgreSQL (prod).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import database_url

# Columns a version row is allowed to transition (everything else is frozen).
MUTABLE_VERSION_COLUMNS = {"status", "change_reason"}


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs = {"connect_args": connect_args, "future": True}
    if not url.startswith("sqlite"):
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = int(os.environ.get("MOTEN_DB_POOL_RECYCLE_SECONDS", "1800"))
        kwargs["pool_size"] = int(os.environ.get("MOTEN_DB_POOL_SIZE", "5"))
        kwargs["max_overflow"] = int(os.environ.get("MOTEN_DB_MAX_OVERFLOW", "5"))
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_con, _record):  # noqa: ANN001
            cur = dbapi_con.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _immutable_tables(metadata) -> list:
    return [t for t in metadata.sorted_tables if t.info.get("immutable")]


def install_immutability_triggers(engine: Engine) -> None:
    """Emit DELETE/UPDATE guard triggers for every table marked immutable."""
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for table in _immutable_tables(engine.metadata if hasattr(engine, "metadata") else Base.metadata):
            _install_for_table(conn, dialect, table)


def _install_for_table(conn, dialect: str, table) -> None:  # noqa: ANN001
    name = table.name
    frozen = [c.name for c in table.columns if c.name not in MUTABLE_VERSION_COLUMNS]
    if dialect == "sqlite":
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in frozen)
        conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}_no_delete"))
        conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}_immutable"))
        conn.execute(
            text(
                f"CREATE TRIGGER trg_{name}_no_delete BEFORE DELETE ON {name} "
                f"BEGIN SELECT RAISE(ABORT, 'immutable version row: delete forbidden'); END"
            )
        )
        conn.execute(
            text(
                f"CREATE TRIGGER trg_{name}_immutable BEFORE UPDATE ON {name} "
                f"FOR EACH ROW WHEN ({changed}) "
                f"BEGIN SELECT RAISE(ABORT, 'immutable version row: only status/change_reason may transition'); END"
            )
        )
    elif dialect == "postgresql":
        checks = " OR ".join(f"OLD.{c} IS DISTINCT FROM NEW.{c}" for c in frozen)
        conn.execute(
            text(
                f"CREATE OR REPLACE FUNCTION fn_{name}_immutable() RETURNS trigger AS $$ "
                f"BEGIN IF (TG_OP = 'DELETE') THEN RAISE EXCEPTION 'immutable version row: delete forbidden'; END IF; "
                f"IF ({checks}) THEN RAISE EXCEPTION 'immutable version row: only status/change_reason may transition'; END IF; "
                f"RETURN NEW; END; $$ LANGUAGE plpgsql;"
            )
        )
        conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{name}_immutable ON {name}"))
        conn.execute(
            text(
                f"CREATE TRIGGER trg_{name}_immutable BEFORE UPDATE OR DELETE ON {name} "
                f"FOR EACH ROW EXECUTE FUNCTION fn_{name}_immutable();"
            )
        )


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        dialect = engine.dialect.name
        for table in _immutable_tables(Base.metadata):
            _install_for_table(conn, dialect, table)
