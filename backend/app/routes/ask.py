"""
POST /ask — full Week 3 pipeline:

    NL question
        |
        v
    Self-correction loop (max 3 attempts)
        |  validate -> execute -> (on failure) re-prompt LLM -> retry
        v
    Explanation layer (separate LLM call, read-only)
        |  plain-English answer + chart type suggestion
        |  + zero-row sanity check (no overclaiming)
        v
    Evaluation log (every attempt recorded for Week 4 benchmark)
        |
        v
    JSON response to frontend

Per architecture.md §3.6, the self-correction loop is capped at 3 attempts.
After 3 failed attempts, the system returns an honest "couldn't answer
confidently" response — never a guess dressed up as a confident answer.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import get_settings
from ..eval_log import log_query
from ..explainer import ExplanationResult, explain
from ..llm import get_llm
from ..pipeline import PipelineResult, run_pipeline
from ..validator import validate_sql
from ..executor import execute_sql as _execute_sql
from ..schema_context import get_schema


router = APIRouter()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000,
                          description="Plain-English business question")
    question_id: str | None = Field(
        default=None,
        description="Optional benchmark ID (e.g. 'q12'). Used in the evaluation log.",
    )


class AttemptInfo(BaseModel):
    attempt_number: int
    sql: str
    rationale: str
    validation_ok: bool
    validation_error: str | None = None
    execution_ok: bool
    execution_error: str | None = None
    row_count: int = 0
    execution_ms: int = 0


class AskResponse(BaseModel):
    question: str
    question_id: str | None = None
    final_status: str          # success | validation_failed | execution_failed | llm_failed | no_answer
    correction_attempts: int
    final_sql: str | None = None
    rationale: str | None = None
    rows: list[dict[str, Any]] | None = None
    row_count: int | None = None
    truncated: bool = False
    execution_ms: int = 0
    plain_english_answer: str | None = None
    suggested_chart_type: str | None = None
    error: str | None = None
    attempts: list[AttemptInfo] = []
    pipeline: list[str] = []
    # Validation/execution diagnostics (used by /execute; /ask leaves these as None
    # because the attempt history already contains per-attempt validation/execution info).
    validation: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """Full self-correcting pipeline + explanation layer + evaluation log."""
    settings = get_settings()

    # 1. Run the self-correcting pipeline (max 3 attempts).
    result: PipelineResult = run_pipeline(req.question, question_id=req.question_id)

    # 2. If success, run the explanation layer.
    explanation: ExplanationResult | None = None
    if result.final_status == "success":
        try:
            explanation = explain(
                question=req.question,
                sql=result.rewritten_sql or result.final_sql or "",
                rows=result.rows,
                row_count=result.row_count,
                truncated=result.truncated,
            )
        except Exception as e:
            log.warning("Explanation layer failed: %s", e)
            # Fallback: if the LLM call itself failed, we still need to apply
            # the zero-row sanity check — a 0-row result is always no_answer.
            is_zero = result.row_count == 0
            explanation = ExplanationResult(
                plain_english_answer=(
                    "I couldn't find data matching this question. The query "
                    "returned zero rows — this may indicate the date range "
                    "or filter doesn't match any records in the database."
                    if is_zero
                    else "(Explanation layer failed to produce a summary; showing raw result rows.)"
                ),
                suggested_chart_type="none" if is_zero else "table",
                no_answer=is_zero,
            )

    # 3. Determine final status. The explanation layer can downgrade a
    # "success" to "no_answer" if it detected a zero-row sanity failure
    # (e.g. the Week 2 q12 case: SQL executed without error but returned
    # 0 rows for a time-windowed question).
    final_status = result.final_status
    if explanation is not None and explanation.no_answer:
        final_status = "no_answer"

    # 4. Build response.
    response = AskResponse(
        question=req.question,
        question_id=req.question_id,
        final_status=final_status,
        correction_attempts=result.correction_attempts,
        final_sql=result.final_sql,
        rationale=result.rationale,
        rows=result.rows if result.final_status == "success" else None,
        row_count=result.row_count if result.final_status == "success" else None,
        truncated=result.truncated,
        execution_ms=result.execution_ms,
        plain_english_answer=explanation.plain_english_answer if explanation else None,
        suggested_chart_type=explanation.suggested_chart_type if explanation else None,
        error=result.final_error,
        attempts=[
            AttemptInfo(
                attempt_number=a.attempt_number,
                sql=a.sql,
                rationale=a.rationale,
                validation_ok=a.validation_ok,
                validation_error=a.validation_error,
                execution_ok=a.execution_ok,
                execution_error=a.execution_error,
                row_count=a.row_count,
                execution_ms=a.execution_ms,
            )
            for a in result.attempts
        ],
        pipeline=result.pipeline,
    )

    # 5. Log to query_log (best-effort — failures here don't break the request).
    log_query(
        question=req.question,
        question_id=req.question_id,
        llm_provider=settings.llm_provider,
        final_status=final_status,
        correction_attempts=result.correction_attempts,
        final_sql=result.final_sql,
        rationale=result.rationale,
        row_count=result.row_count if result.final_status == "success" else None,
        execution_ms=result.execution_ms,
        truncated=result.truncated,
        plain_english_answer=explanation.plain_english_answer if explanation else None,
        suggested_chart_type=explanation.suggested_chart_type if explanation else None,
        final_error=result.final_error,
        attempts=[asdict(a) for a in result.attempts],
        pipeline=result.pipeline,
    )

    return response


# ---------------------------------------------------------------------------
# POST /execute — re-run an edited SQL string directly (no LLM generation).
#
# This endpoint powers the frontend's "edit SQL and re-run" feature on the
# collapsible SQL panel. It bypasses the LLM generation step (the user
# already has SQL they want to test), but STILL goes through the full
# validator + read-only execution + explanation path. The non-negotiable
# safety properties are preserved:
#   - AST validation (SELECT-only, schema cross-check, LIMIT enforcement)
#   - Read-only execution with timeout
#   - Zero-row sanity check + honest no_answer response
# The LLM is used only for the explanation layer (separate call, read-only).
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=20000,
                     description="SQL to execute directly (no LLM generation).")


@router.post("/execute", response_model=AskResponse)
def execute(req: ExecuteRequest) -> AskResponse:
    """Re-run an edited SQL string. Skips LLM generation; preserves all safety."""
    settings = get_settings()

    # 1. Validate (same gate as /ask).
    tables = get_schema()
    vres = validate_sql(req.sql, schema_tables=tables)

    validation_info = {
        "ok": vres.ok,
        "limit_injected": vres.limit_injected,
        "limit_shrunk": vres.limit_shrunk,
        "rejected_table": vres.rejected_table,
        "rejected_column": vres.rejected_column,
        "error": vres.error,
    }

    if not vres.ok:
        return AskResponse(
            question="(edited SQL re-run)",
            final_status="validation_failed",
            correction_attempts=0,
            final_sql=req.sql,
            validation=validation_info,  # type: ignore[arg-type]
            error=f"Query rejected by validator: {vres.error}",
            pipeline=["execute_endpoint", "validate", "done(validation_failed)"],
        )

    # 2. Execute.
    safe_sql = vres.rewritten_sql or req.sql
    eres = _execute_sql(safe_sql)

    execution_info = {
        "ok": eres.ok,
        "row_count": eres.row_count,
        "truncated": eres.truncated,
        "execution_ms": eres.execution_ms,
        "error": eres.error,
    }

    if not eres.ok:
        return AskResponse(
            question="(edited SQL re-run)",
            final_sql=safe_sql,
            validation=validation_info,  # type: ignore[arg-type]
            execution=execution_info,  # type: ignore[arg-type]
            final_status="execution_failed",
            correction_attempts=0,
            error=f"Query execution failed: {eres.error}",
            pipeline=["execute_endpoint", "validate", "execute", "done(execution_failed)"],
        )

    # 3. Explanation layer (still uses LLM, still read-only).
    explanation: ExplanationResult | None = None
    try:
        explanation = explain(
            question="(edited SQL re-run)",
            sql=safe_sql,
            rows=eres.rows,
            row_count=eres.row_count,
            truncated=eres.truncated,
        )
    except Exception as e:
        log.warning("Explanation layer failed on /execute: %s", e)
        is_zero = eres.row_count == 0
        explanation = ExplanationResult(
            plain_english_answer=(
                "I couldn't find data matching this question. The query "
                "returned zero rows — this may indicate the date range "
                "or filter doesn't match any records in the database."
                if is_zero
                else "(Explanation layer failed; showing raw result rows.)"
            ),
            suggested_chart_type="none" if is_zero else "table",
            no_answer=is_zero,
        )

    final_status = "success"
    if explanation.no_answer:
        final_status = "no_answer"

    # 4. Build response (matches AskResponse shape).
    response = AskResponse(
        question="(edited SQL re-run)",
        final_status=final_status,
        correction_attempts=0,
        final_sql=safe_sql,
        rows=eres.rows,
        row_count=eres.row_count,
        truncated=eres.truncated,
        execution_ms=eres.execution_ms,
        plain_english_answer=explanation.plain_english_answer,
        suggested_chart_type=explanation.suggested_chart_type,
        validation=validation_info,  # type: ignore[arg-type]
        execution=execution_info,  # type: ignore[arg-type]
        attempts=[
            AttemptInfo(
                attempt_number=1,
                sql=req.sql,
                rationale="(user-edited SQL)",
                validation_ok=True,
                validation_error=None,
                execution_ok=True,
                execution_error=None,
                row_count=eres.row_count,
                execution_ms=eres.execution_ms,
            )
        ],
        pipeline=["execute_endpoint", "validate", "execute", "explain", "done"],
    )

    # 5. Log.
    log_query(
        question="(edited SQL re-run)",
        llm_provider=settings.llm_provider,
        final_status=final_status,
        correction_attempts=0,
        final_sql=safe_sql,
        row_count=eres.row_count,
        execution_ms=eres.execution_ms,
        truncated=eres.truncated,
        plain_english_answer=explanation.plain_english_answer,
        suggested_chart_type=explanation.suggested_chart_type,
        attempts=[{
            "attempt_number": 1,
            "sql": req.sql,
            "rationale": "(user-edited SQL)",
            "validation_ok": True,
            "execution_ok": True,
            "row_count": eres.row_count,
            "execution_ms": eres.execution_ms,
        }],
        pipeline=response.pipeline,
    )

    return response
