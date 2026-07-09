"""
Adversarial tests for the SQL validator.

Per implementation-plan.md Definition of Done:
    "Zero unsafe queries execute against the DB, even under adversarial test
     questions ('delete all orders', 'drop the customers table')"

Run:
    cd backend
    .venv/bin/python -m scripts.test_validator_adversarial

Exits non-zero if ANY adversarial input passes validation.
"""
from __future__ import annotations

import sys

from app.validator import validate_sql


# ---------------------------------------------------------------------------
# Adversarial inputs — each MUST be rejected by the validator.
# ---------------------------------------------------------------------------

ADVERSARIAL: list[tuple[str, str]] = [
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
    # DML hidden in subquery
    ("SELECT * FROM (DELETE FROM customers RETURNING *) AS x", "DML in subquery"),
    # Comments hiding DML (sqlglot strips comments — should parse as single SELECT)
    ("SELECT * FROM customers -- ; DROP TABLE customers;",
     "Comment-hiding DROP (sqlglot should strip)"),
    # Hallucinated table
    ("SELECT * FROM nonexistent_table", "Hallucinated table"),
    ("SELECT * FROM customerz", "Misspelled table name"),
    # Hallucinated column
    ("SELECT first_name, evil_column FROM customers", "Hallucinated column"),
    ("SELECT customer_name FROM customers", "Plausible-sounding fake column"),
    # Wrong alias
    ("SELECT x.first_name FROM customers c", "Wrong alias qualifier"),
    # Empty
    ("", "Empty SQL"),
    ("   ", "Whitespace-only SQL"),
]


# ---------------------------------------------------------------------------
# Valid inputs — each MUST pass validation. These catch false positives.
# ---------------------------------------------------------------------------

VALID: list[tuple[str, str]] = [
    ("SELECT * FROM customers LIMIT 10", "Simple SELECT"),
    ("SELECT first_name, last_name FROM customers WHERE is_active = 1 LIMIT 50",
     "SELECT with WHERE"),
    ("WITH x AS (SELECT 1 AS n) SELECT * FROM x LIMIT 1", "CTE"),
    ("SELECT * FROM customers UNION ALL SELECT * FROM customers LIMIT 10",
     "UNION ALL"),
    # No LIMIT — validator should auto-inject
    ("SELECT first_name FROM customers", "No LIMIT (auto-inject)"),
    # LIMIT too high — validator should shrink
    ("SELECT * FROM customers LIMIT 999999", "LIMIT too high (shrink)"),
    # Realistic benchmark-style query
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


def run() -> int:
    print("=" * 70)
    print("ADVERSARIAL INPUTS — all MUST be rejected")
    print("=" * 70)
    failures = 0
    for sql, label in ADVERSARIAL:
        result = validate_sql(sql)
        status = "PASS" if not result.ok else "FAIL(allowed!)"
        if result.ok:
            failures += 1
        print(f"  [{status}] {label}")
        print(f"         SQL: {sql[:80]}{'...' if len(sql) > 80 else ''}")
        if result.ok:
            print(f"         !!! Validator allowed: {sql!r}")
        else:
            print(f"         error: {result.error}")

    print()
    print("=" * 70)
    print("VALID INPUTS — all MUST pass")
    print("=" * 70)
    for sql, label in VALID:
        result = validate_sql(sql)
        status = "PASS" if result.ok else "FAIL(rejected!)"
        if not result.ok:
            failures += 1
        print(f"  [{status}] {label}")
        if not result.ok:
            print(f"         SQL: {sql[:80]}{'...' if len(sql) > 80 else ''}")
            print(f"         error: {result.error}")
        else:
            flags = []
            if result.limit_injected:
                flags.append("LIMIT injected")
            if result.limit_shrunk:
                flags.append("LIMIT shrunk")
            if flags:
                print(f"         ({', '.join(flags)})")

    print()
    print("=" * 70)
    if failures == 0:
        print(f"RESULT: All {len(ADVERSARIAL)} adversarial inputs blocked, "
              f"all {len(VALID)} valid inputs accepted.")
        return 0
    else:
        print(f"RESULT: {failures} failure(s) — see above.")
        return 1


if __name__ == "__main__":
    sys.exit(run())
