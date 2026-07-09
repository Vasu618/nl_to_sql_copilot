"""
Explanation Layer — per architecture.md §3.7.

Takes the raw result set (JSON rows) and re-prompts the LLM to produce:
  1. A 1-2 sentence plain-English answer to the original question
  2. A suggested chart type (bar / line / table / none)

Kept as a SEPARATE LLM call from SQL generation, so this step has zero
ability to alter data — it's read-only, purely descriptive. The SQL was
already executed; this layer only describes what came back.

This layer also implements the zero-row sanity check (architecture.md's
"never return a guess dressed up as a confident answer" rule):

  - If a time-windowed question returns 0 rows, the explanation layer
    does NOT fabricate a plausible-sounding answer. Instead it honestly
    reports that no data was found for the requested period, and the
    pipeline marks the request `no_answer` for the evaluation log.
  - This catches the Week 2 silent-failure case (q12: SQL used
    `date('now', ...)` which resolved to 2026, outside the data range,
    silently returning 0 rows).

CHART-TYPE DECISION (hybrid: deterministic rule + LLM judgment)
---------------------------------------------------------------
Per the user's Week 3a sign-off, the chart-type decision uses a
deterministic rule-based fallback ON TOP of the LLM's judgment. When
the LLM's choice conflicts with a clear deterministic rule, the
deterministic rule wins. This is the same "never fully trust LLM
judgment where a hard rule can replace it" principle already used for
SQL safety (validator) — applied consistently to the explanation layer.

Rules (evaluated in order, first match wins):
  1. row_count == 0                                  -> "none"
  2. exactly 1 row AND exactly 1 column              -> "none" (single scalar)
  3. >=2 rows AND col[0] parses as date AND col[1]
     is numeric                                      -> "line" (time series)
  4. 2-7 rows AND 2 columns AND col[0] is string AND
     col[1] is numeric                               -> "bar" (categorical)
  5. otherwise                                       -> LLM's choice (or "table"
                                                        if the LLM's choice is
                                                        invalid)

The LLM is still asked for its choice — its judgment is used for cases
outside the ruleset (e.g., pie chart for part-of-whole with <=7
categories, table for many-column detail rows).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .llm import get_llm

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExplanationResult:
    plain_english_answer: str
    suggested_chart_type: str  # "bar" | "line" | "pie" | "table" | "none"
    # "no_answer" means the explanation layer determined the question couldn't
    # be confidently answered (e.g. zero rows for a time-windowed question).
    # The pipeline uses this to set final_status="no_answer" in the eval log.
    no_answer: bool = False
    raw_response: str | None = None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

EXPLANATION_SYSTEM_PROMPT = """\
You are an analytics explanation layer. You will be given:
  1. The user's original question (plain English).
  2. The SQL that was executed to answer it.
  3. The result rows returned by the database.

Your job: produce a 1-2 sentence plain-English answer to the original
question, based ONLY on the result rows. Do not speculate beyond what the
data shows. Then suggest the most appropriate chart type for visualizing
the result.

CRITICAL — anti-overclaiming rules:
- If the result set is empty (zero rows), DO NOT invent an answer. Instead
  say exactly: "I couldn't find data matching this question. The query
  returned zero rows — this may indicate the date range or filter doesn't
  match any records in the database." Set chart_type to "none".
- If the question asks about a trend or comparison but the data shows no
  meaningful difference, say so honestly. Do not invent a trend.
- If the question asks "did X change significantly" and the data shows a
  tiny change, say "no significant change" — do not overclaim.
- Never use numbers that aren't in the result rows. If you mention a
  number, it must appear in the data.

CHART TYPE GUIDANCE:
- "bar"    — categorical comparison (e.g. revenue by region)
- "line"   — time series (e.g. orders per month)
- "pie"    — part-of-whole with <=7 categories (e.g. payment method share)
- "table"  — many columns, mixed types, or detail-level rows
- "none"   — single scalar value, empty result, or non-numeric answer

Output ONLY valid JSON in this exact format (no prose, no markdown):
{"answer": "<1-2 sentence plain-English answer>",
 "chart_type": "<bar|line|pie|table|none>"}
"""


# ---------------------------------------------------------------------------
# Deterministic chart-type rules (per user's Week 3a sign-off)
# ---------------------------------------------------------------------------

def _is_date_like(v: Any) -> bool:
    """Heuristic: does this value look like a date or timestamp?

    Accepts:
      - ISO date strings: '2025-01-15', '2025-01-15T10:30:00'
      - YYYY-MM strings: '2025-01' (common in monthly aggregations)
      - datetime/date objects (already serialized to ISO string by executor)
    """
    if v is None:
        return False
    if isinstance(v, (datetime,)):
        return True
    s = str(v)
    # YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    if re.match(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$", s):
        return True
    # YYYY-MM (monthly aggregation)
    if re.match(r"^\d{4}-\d{2}$", s):
        return True
    return False


def _is_numeric(v: Any) -> bool:
    """True if v is a number (int, float, Decimal — but NOT bool)."""
    if isinstance(v, bool):
        return False  # bools aren't chartable as numeric
    if isinstance(v, (int, float)):
        return True
    # Strings that parse as numbers (rare in our data, but defensive)
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def deterministic_chart_type(
    rows: list[dict[str, Any]],
    row_count: int,
) -> str | None:
    """Apply hard rules to determine chart type from result shape.

    Returns one of {"none", "line", "bar"} if a rule matches, or None if no
    rule applies (caller should fall back to LLM judgment).

    Rules (evaluated in order, first match wins):
      1. row_count == 0                                -> "none"
      2. exactly 1 row AND exactly 1 column            -> "none" (scalar)
      3. >=2 rows AND col[0] is date AND col[1] numeric -> "line" (time series)
      4. 2-7 rows AND 2 cols AND col[0] string AND
         col[1] numeric                                -> "bar" (categorical)
      5. otherwise                                     -> None (defer to LLM)
    """
    # Rule 1: empty result
    if row_count == 0:
        return "none"

    # Use the actual rows we have (may be a sample if truncated, but the
    # column structure is what matters).
    sample = rows[:7] if rows else []

    # Need at least one row to inspect columns
    if not sample:
        return None

    # Get column order from the first row (dicts in Python 3.7+ preserve
    # insertion order, and SQLAlchemy row._mapping does too).
    columns = list(sample[0].keys())
    n_cols = len(columns)

    # Rule 2: single scalar (1x1)
    if row_count == 1 and n_cols == 1:
        return "none"

    # Rule 3: time series — first col date-like, second col numeric
    if n_cols >= 2 and len(sample) >= 2:
        col0_values = [r.get(columns[0]) for r in sample]
        col1_values = [r.get(columns[1]) for r in sample]
        if all(_is_date_like(v) for v in col0_values) and \
           all(_is_numeric(v) for v in col1_values):
            return "line"

    # Rule 4: categorical comparison — 2-7 rows total, 2 cols, string + numeric.
    # Note: we check row_count (the TOTAL, not the sample size) so truncated
    # results with >7 rows don't accidentally trigger the bar rule on a 7-row
    # sample. The sample is only used for column-type inspection.
    if 2 <= row_count <= 7 and n_cols == 2:
        col0_values = [r.get(columns[0]) for r in sample]
        col1_values = [r.get(columns[1]) for r in sample]
        col0_is_string = all(v is not None and not _is_numeric(v) and not _is_date_like(v)
                             for v in col0_values)
        col1_is_numeric = all(_is_numeric(v) for v in col1_values)
        if col0_is_string and col1_is_numeric:
            return "bar"

    # No rule matched — defer to LLM judgment.
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain(
    question: str,
    sql: str,
    rows: list[dict[str, Any]],
    *,
    row_count: int,
    truncated: bool = False,
) -> ExplanationResult:
    """Generate a plain-English explanation of the result set.

    Args:
        question: the user's original question.
        sql: the executed SQL (for context — the explanation layer never
             re-executes anything).
        rows: the result rows (already serialized to JSON-friendly types).
        row_count: total rows returned (may be > len(rows) if truncated).
        truncated: True if the row_cap was hit.

    Returns:
        ExplanationResult with plain_english_answer, suggested_chart_type,
        and a no_answer flag for the eval log.
    """
    llm = get_llm()

    # Build a compact user prompt: cap rows at 20 so we don't blow up tokens.
    sample_rows = rows[:20]
    user_prompt = (
        f"QUESTION:\n{question}\n\n"
        f"SQL EXECUTED:\n{sql}\n\n"
        f"RESULT ROWS ({row_count} total"
        + (f", showing first {len(sample_rows)}" if row_count > len(sample_rows) else "")
        + (", TRUNCATED at row cap" if truncated else "")
        + "):\n"
        + json.dumps(sample_rows, default=str, indent=2)
    )

    raw = llm.chat(EXPLANATION_SYSTEM_PROMPT, user_prompt, max_tokens=512)
    parsed = _extract_explanation_json(raw)

    # Apply deterministic chart-type rule. If a rule matches and conflicts
    # with the LLM's choice, the rule wins. This is the same "never fully
    # trust LLM judgment where a hard rule can replace it" principle used
    # for SQL safety (validator).
    rule_chart = deterministic_chart_type(rows, row_count)
    if rule_chart is not None:
        if rule_chart != parsed.suggested_chart_type:
            log.info(
                "Chart-type override: LLM chose %s, deterministic rule chose %s — rule wins.",
                parsed.suggested_chart_type, rule_chart,
            )
        parsed.suggested_chart_type = rule_chart

    # Anti-overclaiming safety net: if result is empty and the LLM didn't
    # explicitly say "no data", override to a templated honest response.
    # We trust the LLM's wording when rows exist, but on empty results we
    # enforce a consistent "couldn't answer confidently" message.
    if row_count == 0:
        if not _explicitly_acknowledges_empty(parsed.plain_english_answer):
            parsed = ExplanationResult(
                plain_english_answer=(
                    "I couldn't find data matching this question. The query "
                    "returned zero rows — this may indicate the date range "
                    "or filter doesn't match any records in the database."
                ),
                suggested_chart_type="none",
                no_answer=True,
                raw_response=raw,
            )
        else:
            parsed.no_answer = True

    return parsed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_explanation_json(text: str) -> ExplanationResult:
    """Parse the explanation LLM response. Tolerant of common LLM JSON bugs."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                d = json.loads(m.group(0))
            except json.JSONDecodeError:
                d = {}
        else:
            d = {}

    answer = d.get("answer", "").strip() or "Unable to generate explanation."
    chart = d.get("chart_type", "").strip().lower()
    if chart not in ("bar", "line", "pie", "table", "none"):
        chart = "table"  # safe default

    return ExplanationResult(
        plain_english_answer=answer,
        suggested_chart_type=chart,
        raw_response=text,
    )


def _explicitly_acknowledges_empty(answer: str) -> bool:
    """Heuristic: did the LLM's answer acknowledge that no data was found?"""
    a = answer.lower()
    return any(p in a for p in (
        "zero rows", "no data", "no records", "couldn't find",
        "could not find", "no matching", "no results",
    ))
