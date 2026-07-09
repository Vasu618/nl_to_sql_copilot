"""
Self-correction loop — per architecture.md §3.6.

If validation fails (bad syntax, hallucinated column, disallowed statement)
-> the exact error message is sent back to the LLM as a correction prompt:
"Your query failed because X. Here is the schema again. Fix it."
If the query is valid SQL but the database throws a runtime error -> same loop.

Capped at 3 attempts. After 3 failed attempts, return a clear "couldn't
answer confidently" message instead of guessing.

The loop is the only place where we re-call the LLM with a different
prompt than the initial generation. The correction prompt includes:
  1. The original question
  2. The previous SQL attempt
  3. The specific error message from the validator or DB
  4. A reminder of the schema (truncated for token budget)

The correction prompt does NOT relax any safety rules — every retry goes
through the full validator + read-only execution path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import get_settings
from .executor import ExecutionResult, execute_sql
from .llm import get_llm
from .prompts import build_system_prompt
from .schema_context import get_schema, render_schema_for_prompt
from .validator import ValidationResult, validate_sql

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class AttemptResult:
    """One attempt in the self-correction loop."""
    attempt_number: int          # 1-indexed
    sql: str
    rationale: str
    validation_ok: bool
    validation_error: str | None = None
    limit_injected: bool = False
    limit_shrunk: bool = False
    execution_ok: bool = False
    execution_error: str | None = None
    row_count: int = 0
    execution_ms: int = 0
    truncated: bool = False


@dataclass
class PipelineResult:
    """Final outcome of the full self-correcting pipeline."""
    final_status: str            # success | validation_failed | execution_failed | llm_failed | no_answer
    correction_attempts: int     # 0 if first-try success, 1-3 if retried
    final_sql: str | None = None
    rationale: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    execution_ms: int = 0
    truncated: bool = False
    final_error: str | None = None
    attempts: list[AttemptResult] = field(default_factory=list)
    pipeline: list[str] = field(default_factory=list)
    # Final validated SQL (possibly rewritten by LIMIT injection/shrink)
    rewritten_sql: str | None = None


# ---------------------------------------------------------------------------
# Correction prompt
# ---------------------------------------------------------------------------

CORRECTION_PROMPT_TEMPLATE = """\
Your previous SQL query failed. Here is the original question, your previous \
attempt, and the specific error. Fix the query and return only a new JSON \
object in the same format.

ORIGINAL QUESTION:
{question}

YOUR PREVIOUS SQL (attempt #{attempt_number}):
{previous_sql}

ERROR MESSAGE:
{error_message}

FIX INSTRUCTIONS:
- Address the specific error above. Do not produce the same SQL again.
- The fix must still follow ALL strict rules from the system prompt:
  SELECT-only, exact column names from the schema, include LIMIT, use \
  {dialect}-compatible SQL.
- For function-name typos (e.g. "COLESCE" -> "COALESCE"), correct the spelling.
- For "no such column" errors, check the schema for the correct column name.
- For "no such table" errors, use only tables from the schema.
- For date-related errors, use SQLite-compatible date functions: \
  strftime('%Y-%m', col), date(col, '+N days'), etc. Avoid Postgres-only \
  syntax like DATE_TRUNC and INTERVAL.

Output ONLY valid JSON: {{"sql": "<fixed SQL>", "rationale": "<one-line>"}}
"""


# ---------------------------------------------------------------------------
# JSON extraction (shared with /ask endpoint — keep in sync)
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Tolerant JSON extractor for LLM output. Same logic as routes/ask.py."""
    import json
    import re
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        block = m.group(0)
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            fixed = re.sub(r'"([a-zA-Z_]+)"\s+"', r'"\1": "', block)
            fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass
    sql_m = re.search(r'"sql"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    rat_m = re.search(r'"rationale"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if sql_m:
        try:
            sql = sql_m.group(1).encode().decode("unicode_escape")
        except (UnicodeDecodeError, UnicodeEncodeError):
            sql = sql_m.group(1)
        return {"sql": sql, "rationale": rat_m.group(1) if rat_m else ""}
    raise ValueError(f"Could not extract JSON from LLM response (first 200 chars): {text[:200]}...")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_pipeline(question: str, *, question_id: str | None = None) -> PipelineResult:
    """Run the full self-correcting pipeline for a single question.

    Returns a PipelineResult with the final outcome and full attempt history.
    The /ask endpoint uses this and adds the explanation layer on top.
    """
    settings = get_settings()
    max_attempts = settings.max_correction_attempts  # 3 per architecture.md
    dialect = "sqlite" if settings.database_url.startswith("sqlite") else "postgres"

    pipeline: list[str] = []
    attempts: list[AttemptResult] = []
    pipeline.append("load_schema")
    tables = get_schema()
    schema_text = render_schema_for_prompt(tables)
    system_prompt = build_system_prompt(schema_text=schema_text)

    llm = get_llm()

    # -----------------------------------------------------------------
    # Initial generation
    # -----------------------------------------------------------------
    pipeline.append(f"llm_generate(initial)")
    try:
        raw = llm.chat(system_prompt, question, max_tokens=2048)
    except Exception as e:
        log.exception("LLM initial call failed")
        pipeline.append("done(llm_failed)")
        return PipelineResult(
            final_status="llm_failed",
            correction_attempts=0,
            final_error=f"LLM call failed: {e}",
            attempts=attempts,
            pipeline=pipeline,
        )

    try:
        parsed = _extract_json(raw)
    except ValueError as e:
        pipeline.append("done(llm_failed)")
        return PipelineResult(
            final_status="llm_failed",
            correction_attempts=0,
            final_error=f"LLM output was not valid JSON: {e}",
            attempts=attempts,
            pipeline=pipeline,
        )

    sql = parsed.get("sql", "").strip()
    rationale = parsed.get("rationale", "").strip()

    # -----------------------------------------------------------------
    # Validate -> execute -> (on failure) correct, max 3 attempts
    # -----------------------------------------------------------------
    last_error: str | None = None
    for attempt_num in range(1, max_attempts + 1):
        # Validate
        pipeline.append(f"validate(attempt={attempt_num})")
        vres: ValidationResult = validate_sql(sql, schema_tables=tables)

        attempt = AttemptResult(
            attempt_number=attempt_num,
            sql=sql,
            rationale=rationale,
            validation_ok=vres.ok,
            validation_error=vres.error,
            limit_injected=vres.limit_injected,
            limit_shrunk=vres.limit_shrunk,
        )

        if not vres.ok:
            # Validation failed — this attempt is done; retry if budget remains.
            attempts.append(attempt)
            last_error = vres.error
            if attempt_num < max_attempts:
                pipeline.append(f"correct(attempt={attempt_num+1}, reason=validation)")
                correction_prompt = CORRECTION_PROMPT_TEMPLATE.format(
                    question=question,
                    attempt_number=attempt_num,
                    previous_sql=sql,
                    error_message=vres.error or "Unknown validation error",
                    dialect=dialect,
                )
                try:
                    raw = llm.chat(system_prompt, correction_prompt, max_tokens=2048)
                    parsed = _extract_json(raw)
                    new_sql = parsed.get("sql", "").strip()
                    new_rationale = parsed.get("rationale", "").strip()
                    if not new_sql or new_sql == sql:
                        # LLM couldn't produce a different fix — bail out.
                        break
                    sql, rationale = new_sql, new_rationale
                except Exception as e:
                    log.warning("Correction LLM call failed: %s", e)
                    break
                continue
            else:
                # Out of attempts.
                pipeline.append("done(validation_failed)")
                return PipelineResult(
                    final_status="validation_failed",
                    correction_attempts=attempt_num - 1,
                    final_error=last_error,
                    attempts=attempts,
                    pipeline=pipeline,
                )

        # Validate passed -> execute.
        pipeline.append(f"execute(attempt={attempt_num})")
        safe_sql = vres.rewritten_sql or sql
        attempt.rewritten_sql = safe_sql  # type: ignore[attr-defined]
        eres: ExecutionResult = execute_sql(safe_sql)
        attempt.execution_ok = eres.ok
        attempt.execution_error = eres.error
        attempt.row_count = eres.row_count
        attempt.execution_ms = eres.execution_ms
        attempt.truncated = eres.truncated

        if eres.ok:
            attempts.append(attempt)
            pipeline.append("done(success)")
            return PipelineResult(
                final_status="success",
                correction_attempts=attempt_num - 1,
                final_sql=safe_sql,
                rationale=rationale,
                rows=eres.rows,
                row_count=eres.row_count,
                execution_ms=eres.execution_ms,
                truncated=eres.truncated,
                attempts=attempts,
                pipeline=pipeline,
                rewritten_sql=safe_sql,
            )

        # Execution failed — retry if budget remains.
        attempts.append(attempt)
        last_error = eres.error
        if attempt_num < max_attempts:
            pipeline.append(f"correct(attempt={attempt_num+1}, reason=execution)")
            correction_prompt = CORRECTION_PROMPT_TEMPLATE.format(
                question=question,
                attempt_number=attempt_num,
                previous_sql=safe_sql,
                error_message=eres.error or "Unknown execution error",
                dialect=dialect,
            )
            try:
                raw = llm.chat(system_prompt, correction_prompt, max_tokens=2048)
                parsed = _extract_json(raw)
                new_sql = parsed.get("sql", "").strip()
                new_rationale = parsed.get("rationale", "").strip()
                if not new_sql or new_sql == safe_sql:
                    break
                sql, rationale = new_sql, new_rationale
            except Exception as e:
                log.warning("Correction LLM call failed: %s", e)
                break
            continue
        else:
            pipeline.append("done(execution_failed)")
            return PipelineResult(
                final_status="execution_failed",
                correction_attempts=attempt_num - 1,
                final_error=last_error,
                attempts=attempts,
                pipeline=pipeline,
            )

    # Should not reach here, but defensively:
    pipeline.append("done(no_answer)")
    return PipelineResult(
        final_status="no_answer",
        correction_attempts=max_attempts,
        final_error=last_error or "Could not produce a valid query after max attempts.",
        attempts=attempts,
        pipeline=pipeline,
    )
