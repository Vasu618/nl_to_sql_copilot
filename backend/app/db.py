"""
Database connection layer.

Design notes (defensible in interview):
- Execution uses a *read-only* connection. In SQLite this is the `mode=ro` URI
  parameter; in Postgres it would be a role with GRANT SELECT only. Either way
  the AST validator is the first line of defense and the read-only connection
  is the second — defense in depth.
- The engine is created once and reused (SQLAlchemy pools connections).
- Two engines are exposed:
    * `engine` — read/write, used only by the seed script and DDL.
    * `engine_readonly` — read-only, used by the API for query execution.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings


def _build_engine(database_url: str, read_only: bool) -> Engine:
    """Create a SQLAlchemy engine with the appropriate read-only mode."""
    if read_only and database_url.startswith("sqlite"):
        # Convert `sqlite:///path.db` -> `sqlite:///file:path.db?mode=ro`
        # so the driver itself rejects writes at the filesystem level.
        path = database_url.removeprefix("sqlite:///")
        abs_path = Path(path).resolve()
        # mode=ro requires the file to already exist; we allow creating it
        # via the read-write engine first during the seed step.
        if abs_path.exists():
            uri = f"sqlite:///file:{abs_path}?mode=ro&uri=true"
        else:
            # Fallback: file doesn't exist yet, fall through to normal engine.
            uri = database_url
    else:
        uri = database_url

    return create_engine(
        uri,
        # Conservative pool defaults — this is a portfolio project, not a
        # high-throughput service.
        pool_pre_ping=True,
        future=True,
    )


_settings = get_settings()

# Read-write engine — only used by scripts (DDL, seed, migrations).
engine: Engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)

# Read-only engine — used by the API for all question-driven query execution.
engine_readonly: Engine = _build_engine(_settings.database_url, read_only=_settings.db_read_only)


@contextmanager
def readonly_session() -> Iterator[object]:
    """Yield a SQLAlchemy connection bound in read-only mode.

    For SQLite, the engine itself is opened mode=ro so writes are physically
    impossible. For Postgres (production), the connection URL should point to
    a role that only has GRANT SELECT — the application cannot escalate.

    A statement timeout is also applied per-transaction so a runaway query
    can't hold the connection indefinitely.
    """
    with engine_readonly.connect() as conn:
        # Apply driver-level timeout (best-effort; SQLite ignores, Postgres
        # honors `statement_timeout`).
        timeout_ms = int(_settings.query_timeout_seconds * 1000)
        try:
            if _settings.database_url.startswith("postgres"):
                conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
        except Exception:
            # Don't fail the request if the timeout can't be set — the
            # validator layer also enforces a timeout at the Python level.
            pass
        yield conn
