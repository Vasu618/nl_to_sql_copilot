"""
Evaluation log table — query_log.

Per architecture.md §3.8: "Every question, generated SQL, validation result,
number of correction attempts, and final outcome is logged to a small
query_log table. This is what lets you later say something like '87%
first-try valid SQL rate, 96% after self-correction, across a 30-question
benchmark' — a real, measured number instead of a vague claim."

This table is created in the SAME database as the e-commerce data, but with
a separate name (`query_log`) so the schema-context builder doesn't expose
it to the LLM (we don't want the LLM generating SQL against the log table).

CRITICAL: writes to query_log go through the read-WRITE engine, not the
read-only engine. The execution path for user questions is still read-only;
only the logging path uses the write engine. This separation is enforced
structurally — see log_query() below.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from .db import engine  # read-WRITE engine — only used for logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

QUERY_LOG_DDL = """
CREATE TABLE IF NOT EXISTS query_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Request metadata
    question        TEXT NOT NULL,
    question_id     TEXT,                    -- optional benchmark ID (e.g. "q12")
    timestamp       TIMESTAMP NOT NULL,
    -- LLM provider
    llm_provider    TEXT NOT NULL,
    -- Outcomes
    final_status    TEXT NOT NULL,           -- success | validation_failed | execution_failed | llm_failed | no_answer
    correction_attempts INTEGER NOT NULL DEFAULT 0,
    -- The winning SQL (last attempted; or first if no correction needed)
    final_sql       TEXT,
    -- Rationale from the LLM
    rationale       TEXT,
    -- Result metadata
    row_count       INTEGER,
    execution_ms    INTEGER,
    truncated       BOOLEAN,
    -- Explanation layer output
    plain_english_answer TEXT,
    suggested_chart_type  TEXT,
    -- Error info (for failed/no_answer cases)
    final_error     TEXT,
    -- Full attempt history (JSON array — each entry has attempt#, sql, error)
    attempts_json   TEXT,
    -- Pipeline trace
    pipeline_json   TEXT
)
"""

QUERY_LOG_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_query_log_timestamp ON query_log(timestamp)"
)


def init_query_log() -> None:
    """Create the query_log table if it doesn't exist. Idempotent."""
    with engine.begin() as conn:
        conn.execute(text(QUERY_LOG_DDL))
        conn.execute(text(QUERY_LOG_INDEX))


# ---------------------------------------------------------------------------
# Logging API
# ---------------------------------------------------------------------------

def log_query(
    *,
    question: str,
    question_id: str | None = None,
    llm_provider: str,
    final_status: str,
    correction_attempts: int,
    final_sql: str | None = None,
    rationale: str | None = None,
    row_count: int | None = None,
    execution_ms: int | None = None,
    truncated: bool | None = None,
    plain_english_answer: str | None = None,
    suggested_chart_type: str | None = None,
    final_error: str | None = None,
    attempts: list[dict[str, Any]] | None = None,
    pipeline: list[str] | None = None,
) -> int:
    """Insert a row into query_log. Returns the new log_id.

    Failures in logging are swallowed (just logged) — the user's request
    must not fail because the log couldn't be written. The evaluation log
    is best-effort instrumentation, not a transactional requirement.
    """
    try:
        init_query_log()  # idempotent
        with engine.begin() as conn:
            row = conn.execute(
                text("""INSERT INTO query_log
                        (question, question_id, timestamp, llm_provider,
                         final_status, correction_attempts, final_sql, rationale,
                         row_count, execution_ms, truncated,
                         plain_english_answer, suggested_chart_type,
                         final_error, attempts_json, pipeline_json)
                        VALUES
                        (:question, :qid, :ts, :provider,
                         :status, :attempts, :sql, :rationale,
                         :rc, :ms, :trunc,
                         :answer, :chart,
                         :err, :attempts_json, :pipeline_json)
                        RETURNING log_id"""),
                {
                    "question": question,
                    "qid": question_id,
                    "ts": datetime.now(timezone.utc),
                    "provider": llm_provider,
                    "status": final_status,
                    "attempts": correction_attempts,
                    "sql": final_sql,
                    "rationale": rationale,
                    "rc": row_count,
                    "ms": execution_ms,
                    "trunc": truncated,
                    "answer": plain_english_answer,
                    "chart": suggested_chart_type,
                    "err": final_error,
                    "attempts_json": json.dumps(attempts, default=str) if attempts else None,
                    "pipeline_json": json.dumps(pipeline) if pipeline else None,
                },
            ).fetchone()
            return int(row[0])
    except Exception as e:
        log.warning("Failed to write query_log entry: %s", e)
        return -1
