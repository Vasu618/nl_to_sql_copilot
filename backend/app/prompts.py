"""
System prompt + few-shot examples for the SQL generation LLM call.

The prompt enforces the architecture.md §3.4 rules:
- SELECT-only
- Exact column names from the schema (no inventing/abbreviating)
- Always include a LIMIT clause
- Structured JSON output (sql + rationale), no free-form prose
- Dialect-correct SQL (SQLite for dev, Postgres for prod)

The 5 few-shot examples are hand-written and span difficulty levels:
  1. Easy   — single-table filter + aggregation
  2. Easy   — single-table GROUP BY
  3. Medium — two-table join + aggregation
  4. Medium — date-range filter with "last quarter" semantics
  5. Hard   — CTE + self-join + HAVING for "repeat customer" definition

Example 5 is the most important: it demonstrates the *correct* definition
of "repeat customer" (a customer with >=2 orders in the period), which the
Week 1 checkpoint showed the LLM gets wrong without a demonstration.
"""
from __future__ import annotations

from .schema_context import render_runtime_context, render_schema_for_prompt


# ---------------------------------------------------------------------------
# Few-shot examples — hand-written, dialect-correct for SQLite.
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "question": "What is the total revenue from delivered orders?",
        "rationale": "Sum total_amount over orders with status='delivered'. Single-table aggregation.",
        "sql": (
            "SELECT SUM(total_amount) AS total_revenue "
            "FROM orders "
            "WHERE status = 'delivered' "
            "LIMIT 1"
        ),
    },
    {
        "question": "How many orders has each customer placed?",
        "rationale": "Group orders by customer_id, count rows per group. Single-table GROUP BY.",
        "sql": (
            "SELECT customer_id, COUNT(*) AS order_count "
            "FROM orders "
            "GROUP BY customer_id "
            "ORDER BY order_count DESC "
            "LIMIT 100"
        ),
    },
    {
        "question": "What is the average order value by product category?",
        "rationale": "Join orders -> order_items -> products to attribute revenue to categories, "
                     "then average per-category revenue across orders.",
        "sql": (
            "SELECT p.category, AVG(oi.quantity * oi.unit_price) AS avg_line_value "
            "FROM order_items oi "
            "JOIN products p ON oi.product_id = p.product_id "
            "GROUP BY p.category "
            "ORDER BY avg_line_value DESC "
            "LIMIT 50"
        ),
    },
    {
        "question": "How many orders were placed last month, grouped by payment method?",
        "rationale": "Filter orders to the previous calendar month relative to the data's max date, "
                     "group by payment_method. Uses absolute date strings since the data's max date "
                     "is 2025-12-31, so 'last month' = November 2025.",
        "sql": (
            "SELECT payment_method, COUNT(*) AS order_count "
            "FROM orders "
            "WHERE order_date >= '2025-11-01' "
            "  AND order_date <  '2025-12-01' "
            "GROUP BY payment_method "
            "ORDER BY order_count DESC "
            "LIMIT 50"
        ),
    },
    {
        "question": "Which region had the most repeat customers last quarter?",
        "rationale": "A 'repeat customer' is a customer with >= 2 orders in the period. "
                     "Use a CTE to compute per-customer order counts within the most recent "
                     "quarter with data (2025-Q4 = Oct-Dec 2025), filter to those with >= 2, "
                     "then count by region via the customers -> regions join. "
                     "Note: 'last quarter' is resolved relative to the data's max date, not today.",
        "sql": (
            "WITH quarterly_orders AS (\n"
            "  SELECT o.customer_id, COUNT(*) AS order_count\n"
            "  FROM orders o\n"
            "  WHERE o.order_date >= '2025-10-01'\n"
            "    AND o.order_date <  '2026-01-01'\n"
            "  GROUP BY o.customer_id\n"
            "  HAVING COUNT(*) >= 2\n"
            ")\n"
            "SELECT r.region_name, COUNT(*) AS repeat_customers\n"
            "FROM quarterly_orders qo\n"
            "JOIN customers c ON c.customer_id = qo.customer_id\n"
            "JOIN regions   r ON r.region_id   = c.region_id\n"
            "GROUP BY r.region_name\n"
            "ORDER BY repeat_customers DESC\n"
            "LIMIT 10"
        ),
    },
]


def _render_few_shot() -> str:
    """Render few-shot examples as JSON-formatted Q/A pairs."""
    import json
    lines = ["FEW-SHOT EXAMPLES (question -> JSON output):"]
    for i, ex in enumerate(FEW_SHOT_EXAMPLES, 1):
        lines.append(f"\nExample {i}:")
        lines.append(f"Question: {ex['question']}")
        # Note: the rationale field is part of the EXPECTED output format,
        # so we include it in the JSON the model should produce.
        out = {"sql": ex["sql"], "rationale": ex["rationale"]}
        lines.append(f"Output: {json.dumps(out)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembled system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are a SQL query generator for an e-commerce analytics database.

Your job: given a plain-English business question, produce ONE SQL query that
answers it. The query must run on the database described below.

{runtime_context}

{schema}

{few_shot}

STRICT RULES (any violation makes your output rejected):
1. Output ONLY a single SELECT statement (CTEs and UNION ALL are allowed; \
   INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE are forbidden).
2. Use ONLY table and column names that appear in the schema above. \
   Do not invent, abbreviate, or pluralize column names.
3. Always include a LIMIT clause. The hard cap is {row_limit}; smaller is better \
   when the question asks for a single answer (LIMIT 1) or a small top-N.
4. Use only {dialect}-compatible SQL. Do NOT use Postgres-only syntax \
   (DATE_TRUNC, INTERVAL, EXTRACT(QUARTER FROM ...)) when the dialect is sqlite. \
   Use strftime() and date() functions instead.
5. A "repeat customer" in a period = a customer with >= 2 orders in that period. \
   Always use HAVING COUNT(*) >= 2 (or equivalent) — never assume distinct \
   customers per period are "repeat".
6. "Last quarter" / "last month" / "last year" in user questions refers to the \
   most recent fully-completed period WITH DATA, not relative to today's actual \
   calendar date. Look at the data date range shown in the runtime context. \
   If today is past the data's max date, compute "last quarter" relative to \
   the data's max date, not today. For example, if the data ends 2025-12-31 \
   and the question asks "last quarter", that means 2025-Q4 (Oct-Dec 2025), \
   NOT the quarter relative to today's calendar date.
7. If the question is ambiguous, make a reasonable assumption and note it in the \
   rationale field.
8. Output ONLY valid JSON in this exact format, no prose, no markdown fences:
   {{"sql": "<single SQL string>", "rationale": "<one-line explanation>"}}
"""


def build_system_prompt(schema_text: str | None = None) -> str:
    """Assemble the full system prompt.

    Args:
        schema_text: pre-rendered schema (cached between requests in production).
                     If None, fetches live schema.
    """
    from .config import get_settings
    settings = get_settings()
    dialect = "sqlite" if settings.database_url.startswith("sqlite") else "postgres"

    if schema_text is None:
        schema_text = render_schema_for_prompt()

    return SYSTEM_PROMPT_TEMPLATE.format(
        runtime_context=render_runtime_context(),
        schema=schema_text,
        few_shot=_render_few_shot(),
        row_limit=settings.query_row_limit,
        dialect=dialect,
    )
