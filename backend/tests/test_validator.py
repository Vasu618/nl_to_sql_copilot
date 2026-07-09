"""
Validator tests — verify the sqlglot AST validator blocks unsafe SQL and
allows safe SELECTs.

These are the non-negotiable safety tests. If any of these fail, the system
is NOT safe to deploy — a failure means destructive SQL could execute.
"""
from __future__ import annotations

import pytest

from app.validator import validate_sql
from app.schema_context import get_schema


@pytest.fixture(scope="module")
def schema_tables():
    """Load the live schema once for all tests in this module."""
    return get_schema()


# ---------------------------------------------------------------------------
# Adversarial inputs — must ALL be rejected
# ---------------------------------------------------------------------------

ADVERSARIAL_CASES = [
    # DML
    ("INSERT INTO customers (first_name) VALUES ('evil')", "INSERT"),
    ("UPDATE customers SET first_name='evil'", "UPDATE"),
    ("DELETE FROM customers", "DELETE"),
    ("DELETE FROM orders WHERE 1=1", "DELETE with WHERE"),
    # DDL
    ("DROP TABLE customers", "DROP"),
    ("DROP TABLE IF EXISTS orders", "DROP IF EXISTS"),
    ("ALTER TABLE customers ADD COLUMN evil TEXT", "ALTER"),
    ("CREATE TABLE evil (id INTEGER)", "CREATE"),
    ("TRUNCATE TABLE customers", "TRUNCATE"),
    # Multi-statement injection
    ("SELECT * FROM customers; DROP TABLE customers;", "Multi-statement DROP"),
    ("SELECT * FROM customers; DELETE FROM orders;", "Multi-statement DELETE"),
    ("SELECT * FROM customers;;", "Trailing semicolons"),
    # Comment-hiding attempts
    ("SELECT * FROM customers -- ; DROP TABLE customers;", "Comment-hiding DROP"),
    # Hallucinated schema
    ("SELECT * FROM nonexistent_table", "Hallucinated table"),
    ("SELECT * FROM customerz", "Misspelled table name"),
    ("SELECT first_name, evil_column FROM customers", "Hallucinated column"),
    ("SELECT customer_name FROM customers", "Plausible fake column"),
    ("SELECT x.first_name FROM customers c", "Wrong alias qualifier"),
    # Empty
    ("", "Empty SQL"),
    ("   ", "Whitespace-only SQL"),
]


@pytest.mark.parametrize("sql,label", ADVERSARIAL_CASES)
def test_adversarial_sql_is_rejected(sql, label, schema_tables):
    """Every adversarial SQL input MUST be rejected by the validator."""
    result = validate_sql(sql, schema_tables=schema_tables)
    assert not result.ok, (
        f"FAIL: {label!r} was ALLOWED by the validator.\n"
        f"SQL: {sql}\n"
        f"Validator said: ok={result.ok}, error={result.error}"
    )


# ---------------------------------------------------------------------------
# Forbidden table — query_log must be rejected even though it exists
# ---------------------------------------------------------------------------

def test_query_log_table_is_forbidden(schema_tables):
    """References to the query_log table must be rejected."""
    result = validate_sql(
        "SELECT COUNT(*) FROM query_log LIMIT 10",
        schema_tables=schema_tables,
    )
    assert not result.ok, "query_log access was allowed — this is a security bug"
    assert "forbidden" in result.error.lower() or "query_log" in result.error.lower()


# ---------------------------------------------------------------------------
# Valid inputs — must ALL pass
# ---------------------------------------------------------------------------

VALID_CASES = [
    ("SELECT * FROM customers LIMIT 10", "Simple SELECT"),
    ("SELECT first_name, last_name FROM customers WHERE is_active = 1 LIMIT 50",
     "SELECT with WHERE"),
    ("WITH x AS (SELECT 1 AS n) SELECT * FROM x LIMIT 1", "CTE"),
    ("SELECT * FROM customers LIMIT 5 UNION ALL SELECT * FROM customers LIMIT 5",
     "UNION ALL"),
    ("SELECT first_name FROM customers", "No LIMIT (auto-inject)"),
    ("SELECT * FROM customers LIMIT 999999", "LIMIT too high (shrink)"),
    ("""WITH quarterly_orders AS (
        SELECT o.customer_id, COUNT(*) AS oc
        FROM orders o
        WHERE o.order_date >= '2025-07-01' AND o.order_date < '2025-10-01'
        GROUP BY o.customer_id
        HAVING COUNT(*) >= 2
      )
      SELECT r.region_name, COUNT(*) AS repeat_customers
      FROM quarterly_orders qo
      JOIN customers c ON c.customer_id = qo.customer_id
      JOIN regions r ON r.region_id = c.region_id
      GROUP BY r.region_name
      ORDER BY repeat_customers DESC
      LIMIT 10""", "Repeat-customer by region (CTE + joins)"),
]


@pytest.mark.parametrize("sql,label", VALID_CASES)
def test_valid_sql_is_accepted(sql, label, schema_tables):
    """Every valid SQL input MUST pass validation."""
    result = validate_sql(sql, schema_tables=schema_tables)
    assert result.ok, (
        f"FAIL: {label!r} was REJECTED by the validator.\n"
        f"SQL: {sql}\n"
        f"Validator said: ok={result.ok}, error={result.error}"
    )


# ---------------------------------------------------------------------------
# LIMIT enforcement
# ---------------------------------------------------------------------------

def test_limit_is_auto_injected_when_missing(schema_tables):
    """If the LLM omits LIMIT, the validator must inject one."""
    result = validate_sql(
        "SELECT first_name FROM customers",
        schema_tables=schema_tables,
    )
    assert result.ok
    assert result.limit_injected, "LIMIT should have been auto-injected"
    assert "LIMIT" in result.rewritten_sql.upper()


def test_limit_is_shrunk_when_too_large(schema_tables):
    """If the LLM's LIMIT exceeds the cap, the validator must shrink it."""
    result = validate_sql(
        "SELECT * FROM customers LIMIT 999999",
        schema_tables=schema_tables,
    )
    assert result.ok
    assert result.limit_shrunk, "LIMIT should have been shrunk"
    # The rewritten SQL should not contain 999999
    assert "999999" not in result.rewritten_sql
