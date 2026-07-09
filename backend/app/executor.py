"""
Read-only query executor.

Per architecture.md non-negotiables:
- Execution uses the read-only engine (driver-level writes are impossible).
- A driver-level timeout is enforced. SQLite doesn't honor
  `statement_timeout` (that's a Postgres concept), so for SQLite we use
  `busy_timeout` plus a Python-level thread-based timeout as the second
  line of defense. Postgres uses `SET LOCAL statement_timeout`.
- A row-limit cap is applied at the Python level (in addition to the
  LIMIT clause the validator injects) — defense in depth.
"""
from __future__ import annotations

import concurrent.futures
import signal
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from .config import get_settings
from .db import engine_readonly


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Outcome of executing a validated SQL query."""
    ok: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None
    truncated: bool = False  # True if results were capped at the row limit
    execution_ms: int = 0


# ---------------------------------------------------------------------------
# Value serialization (for JSON-friendly response)
# ---------------------------------------------------------------------------

def _serialize(v: Any) -> Any:
    """Make a SQL value JSON-serializable."""
    import datetime
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return "<bytes>"
    return v


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

# SQLite is synchronous and blocking; we run it in a worker thread with a
# timeout to enforce the cap regardless of what the DB driver does.
# (For Postgres, statement_timeout at the driver level would be enough,
# but the thread-based timeout still adds defense in depth.)

def execute_sql(sql: str) -> ExecutionResult:
    """Execute a validated SQL string against the read-only DB.

    Args:
        sql: the rewritten, validated SQL string from the validator.

    Returns:
        ExecutionResult. If `ok=False`, `error` is a DB-runtime error
        message suitable for the self-correction loop.
    """
    settings = get_settings()
    row_cap = settings.query_row_limit
    timeout_s = settings.query_timeout_seconds

    # For SQLite: set busy_timeout via PRAGMA on each connection. For Postgres:
    # SET LOCAL statement_timeout. Both are applied inside the worker thread.
    is_sqlite = settings.database_url.startswith("sqlite")

    def _run() -> ExecutionResult:
        with engine_readonly.connect() as conn:
            # Apply driver-level timeout.
            try:
                if is_sqlite:
                    conn.execute(text(f"PRAGMA busy_timeout = {int(timeout_s * 1000)}"))
                else:
                    conn.execute(text(f"SET LOCAL statement_timeout = '{int(timeout_s * 1000)}ms'"))
            except Exception:
                pass  # defense in depth — Python-level timeout is the backstop

            # Stream results to avoid loading the entire result set into
            # memory if the row count is huge (the LIMIT cap protects us,
            # but streaming is still a good practice).
            try:
                result = conn.execute(text(sql))
            except Exception as e:
                return ExecutionResult(ok=False, error=f"DB execution error: {e}")

            rows: list[dict[str, Any]] = []
            truncated = False
            try:
                for i, row in enumerate(result):
                    if i >= row_cap:
                        truncated = True
                        break
                    rows.append({k: _serialize(v) for k, v in dict(row._mapping).items()})
            except Exception as e:
                # Some drivers raise during fetch if the query was killed
                # mid-stream. Treat as a timeout.
                return ExecutionResult(ok=False, error=f"DB fetch error: {e}")

            return ExecutionResult(
                ok=True,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
            )

    # Run with Python-level timeout (catches runaway queries even on SQLite).
    start = __import__("time").perf_counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            try:
                result = future.result(timeout=timeout_s + 0.5)
            except concurrent.futures.TimeoutExpired:
                return ExecutionResult(
                    ok=False,
                    error=f"Query exceeded the {timeout_s}s execution timeout.",
                )
    except Exception as e:
        return ExecutionResult(ok=False, error=f"Executor error: {e}")

    result.execution_ms = int((__import__("time").perf_counter() - start) * 1000)
    return result
