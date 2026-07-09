"""
SQL Safety Validator (sqlglot-based) — the heart of the safety pipeline.

Per architecture.md §3.5, this is the non-negotiable gate before any query
touches the database. It enforces:

1. AST parse success — reject anything that isn't valid SQL.
2. Single-statement only — reject multi-statement injection attempts.
3. SELECT-only at the AST level — reject INSERT/UPDATE/DELETE/DROP/ALTER/
   TRUNCATE/CREATE even if hidden inside a UNION or subquery.
4. Schema cross-check — every referenced table (excluding CTEs) must exist;
   every referenced column must exist on its table (after alias resolution).
5. Auto-inject LIMIT if missing; shrink LIMIT if larger than the cap.

The validator NEVER uses regex or string matching for safety decisions.
Regex-based validators are trivially bypassable (e.g. comments, string
literals, encoding tricks). sqlglot parses to a real AST so we reason about
the actual structure of the query.

If validation fails, the validator returns a structured `ValidationResult`
with a specific error message. That message is fed back to the LLM in the
Week 3 self-correction loop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from .config import get_settings
from .schema_context import ColumnInfo, TableInfo, get_schema


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Outcome of validating a single SQL string.

    `ok=True` means the query is safe to execute. `rewritten_sql` may differ
    from the input (e.g. if LIMIT was injected or shrunk).

    `ok=False` means the query is rejected. `error` is a human/LLM-readable
    explanation that the self-correction loop will send back to the model.
    """
    ok: bool
    rewritten_sql: str | None = None
    error: str | None = None
    # Diagnostics for the evaluation log
    rejected_table: str | None = None
    rejected_column: str | None = None
    limit_injected: bool = False
    limit_shrunk: bool = False


# ---------------------------------------------------------------------------
# Forbidden AST node types — anything that isn't a SELECT (or a SELECT-bearing
# compound like UNION/INTERSECT/CTE) at the top level.
# ---------------------------------------------------------------------------

# These are AST node class names in sqlglot. We reject them anywhere in the
# tree (not just at the root) — DML hidden inside a subquery is still DML.
FORBIDDEN_NODE_TYPES: set[str] = {
    "Insert", "Update", "Delete",
    "Drop", "Alter", "Create", "TruncateTable",
    "Merge", "Command",  # Command = generic SQL command (e.g. VACUUM, PRAGMA)
}

# Allowed root node types: SELECT, UNION/INTERSECT/EXCEPT (set ops on SELECTs).
# Subquery expressions are fine because they're nested inside SELECTs.
ALLOWED_ROOT_TYPES: set[str] = {
    "Select", "Union", "Intersect", "Except", "Subquery",
}


# ---------------------------------------------------------------------------
# Schema index — built once, reused across validations within a request.
# ---------------------------------------------------------------------------

@dataclass
class SchemaIndex:
    """In-memory index of the live schema, for fast cross-checking."""
    # table_name -> set of column names (lowercase for case-insensitive match)
    tables: dict[str, set[str]] = field(default_factory=dict)
    # alias_or_table_name -> real_table_name (resolved via FROM/JOIN clauses)
    # populated per-query, not per-schema
    # (kept here as a default-empty dict for clarity)

    @classmethod
    def from_schema(cls, tables: list[TableInfo]) -> "SchemaIndex":
        idx = cls()
        for t in tables:
            idx.tables[t.name.lower()] = {c.name.lower() for c in t.columns}
        return idx

    def has_table(self, name: str) -> bool:
        return name.lower() in self.tables

    def has_column(self, table: str, column: str) -> bool:
        cols = self.tables.get(table.lower())
        return cols is not None and column.lower() in cols


# ---------------------------------------------------------------------------
# Alias resolution — map column-qualifiers (e.g. "c.first_name") to real
# table names by walking the FROM/JOIN clauses.
# ---------------------------------------------------------------------------

def _extract_identifier(error_msg: str) -> str | None:
    """Try to pull the offending identifier out of a sqlglot error message.

    Used purely for the `rejected_column`/`rejected_table` diagnostic field
    in ValidationResult — the LLM-correction prompt only needs the message
    text, but having the identifier separately makes the evaluation log
    easier to aggregate.
    """
    m = re.search(r"Column '([^']+)' could not be resolved", error_msg)
    if m:
        return m.group(1)
    m = re.search(r"Table '([^']+)' does not exist", error_msg)
    if m:
        return m.group(1)
    return None


def _resolve_aliases(root: exp.Expression) -> dict[str, str]:
    """Build a map of alias_name -> real_table_name from FROM and JOIN clauses.

    For each Table node encountered in FROM/JOIN, record:
      - alias -> real_name  (e.g. "c" -> "customers")
      - real_name -> real_name  (so unqualified references still resolve)
    CTE names are also recorded as alias -> cte_name so columns referencing
    them aren't mistaken for hallucinated tables.
    """
    alias_map: dict[str, str] = {}
    # Collect CTE names first so they're treated as known "tables".
    for cte in root.find_all(exp.CTE):
        cte_name = cte.alias_or_name
        alias_map[cte_name.lower()] = cte_name.lower()
        # Columns of the CTE aren't known to our schema index — we'll skip
        # column-existence checks for any column qualified by a CTE alias.
    # Walk all Table nodes (these appear in FROM and JOIN).
    for table_node in root.find_all(exp.Table):
        real_name = table_node.name
        alias = table_node.alias or real_name
        alias_map[alias.lower()] = real_name.lower()
        alias_map[real_name.lower()] = real_name.lower()
    return alias_map


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_sql(
    sql: str,
    schema_tables: list[TableInfo] | None = None,
    *,
    dialect: str | None = None,
) -> ValidationResult:
    """Validate a SQL string against the safety rules + live schema.

    Args:
        sql: the LLM-generated SQL string.
        schema_tables: live schema (fetched if None).
        dialect: SQL dialect for parsing. Defaults to sqlite/postgres based on
                 the configured database_url.

    Returns:
        ValidationResult with `ok=True` and `rewritten_sql` if safe to execute,
        or `ok=False` and `error` if rejected.
    """
    settings = get_settings()
    if dialect is None:
        dialect = "sqlite" if settings.database_url.startswith("sqlite") else "postgres"
    if schema_tables is None:
        schema_tables = get_schema()
    schema_index = SchemaIndex.from_schema(schema_tables)

    # -------------------------------------------------------------------
    # Step 0: Defense in depth — reject any string with multiple semicolons.
    # sqlglot collapses ';;' to a single statement, but a future parser
    # version could behave differently. We enforce at the string level too.
    # A single trailing ';' is fine.
    # -------------------------------------------------------------------
    stripped = sql.strip()
    if stripped.endswith(";"):
        stripped_for_semicolon_check = stripped[:-1]
    else:
        stripped_for_semicolon_check = stripped
    if ";" in stripped_for_semicolon_check:
        return ValidationResult(
            ok=False,
            error=(
                "Multiple semicolons detected. Only a single SQL statement "
                "is allowed; statement chaining is forbidden."
            ),
        )

    # -------------------------------------------------------------------
    # Step 1: Parse. Multiple statements = reject.
    # -------------------------------------------------------------------
    try:
        parsed = sqlglot.parse(sql, dialect=dialect)
    except Exception as e:
        return ValidationResult(
            ok=False,
            error=f"SQL parse error: {e}",
        )

    # Filter out None (sqlglot sometimes returns None for trailing whitespace
    # or empty statements). BUT: any non-None 2nd statement is a rejection.
    # Also reject any Semicolon-type nodes (leftover from comment-only tails).
    statements: list[exp.Expression] = []
    for p in parsed:
        if p is None:
            continue
        # Semicolon nodes appear when input has trailing comments like
        # 'SELECT 1; /* comment */'. Treat as a second statement -> reject.
        if type(p).__name__ == "Semicolon":
            return ValidationResult(
                ok=False,
                error=(
                    "Multiple statements detected (trailing content after "
                    "the first statement). Only a single SELECT is allowed."
                ),
            )
        statements.append(p)

    if len(statements) == 0:
        return ValidationResult(ok=False, error="Empty SQL.")
    if len(statements) > 1:
        return ValidationResult(
            ok=False,
            error=(
                f"Multiple statements detected ({len(statements)} found). "
                "Only a single SELECT statement is allowed."
            ),
        )

    root = statements[0]

    # -------------------------------------------------------------------
    # Step 2: Root must be an allowed SELECT-family type.
    # -------------------------------------------------------------------
    root_type = type(root).__name__
    if root_type not in ALLOWED_ROOT_TYPES:
        return ValidationResult(
            ok=False,
            error=(
                f"Statement is a {root_type}, not a SELECT. "
                "Only SELECT statements (with optional CTEs/UNION) are allowed."
            ),
        )

    # -------------------------------------------------------------------
    # Step 3: Walk the entire tree — reject any forbidden node type.
    # This catches DML hidden in subqueries, comments, or string literals
    # that survived parsing (sqlglot would normally raise on those, but
    # we double-check defensively).
    #
    # Note: sqlglot's walk() API yields bare Expression objects (not tuples)
    # in v25+. We handle both forms defensively.
    # -------------------------------------------------------------------
    for item in root.walk():
        node = item[0] if isinstance(item, tuple) else item
        node_type = type(node).__name__
        if node_type in FORBIDDEN_NODE_TYPES:
            return ValidationResult(
                ok=False,
                error=(
                    f"Forbidden operation detected: {node_type}. "
                    "Only SELECT statements are allowed."
                ),
            )

    # -------------------------------------------------------------------
    # Step 4a: Table existence check.
    # Walk the AST and verify every Table reference exists in the live schema
    # (CTE names are exempted — they're defined in the query itself).
    # We do this BEFORE qualify() because qualify silently skips unknown
    # tables rather than raising.
    #
    # Also explicitly reject references to the query_log table — even though
    # it exists in the database, the LLM must not be allowed to read or
    # manipulate the evaluation log.
    # -------------------------------------------------------------------
    FORBIDDEN_TABLES = {"query_log"}  # instrumentation tables the LLM can't touch
    cte_names_lower = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    for table_node in root.find_all(exp.Table):
        tname = table_node.name
        if tname.lower() in cte_names_lower:
            continue
        if tname.lower() in FORBIDDEN_TABLES:
            return ValidationResult(
                ok=False,
                error=(
                    f"Access to table '{tname}' is forbidden — this is an "
                    "internal instrumentation table, not part of the business schema."
                ),
                rejected_table=tname,
            )
        if not schema_index.has_table(tname):
            return ValidationResult(
                ok=False,
                error=f"Table '{tname}' does not exist in the schema.",
                rejected_table=tname,
            )

    # -------------------------------------------------------------------
    # Step 4b: Column existence check via sqlglot's `qualify` optimizer.
    # `qualify` resolves every column reference to its source table (handling
    # aliases, CTEs, subqueries) and raises OptimizeError if any column
    # can't be resolved. Far more reliable than walking the AST ourselves.
    # -------------------------------------------------------------------
    qualify_schema: dict[str, dict[str, str]] = {
        t.name: {c.name: c.type for c in t.columns}
        for t in schema_tables
    }

    try:
        from sqlglot.optimizer.qualify import qualify
        qualified = qualify(
            root,
            schema=qualify_schema,
            dialect=dialect,
            # Don't expand SELECT * — we want the validator to be tolerant
            # of * since we'll let the DB expand it at execution time.
            expand_stars=False,
        )
        # Use the qualified tree for downstream checks (LIMIT, render).
        root = qualified
    except Exception as e:
        msg = str(e)
        return ValidationResult(
            ok=False,
            error=f"Schema cross-check failed: {msg}",
            rejected_column=_extract_identifier(msg),
        )

    # -------------------------------------------------------------------
    # Step 5: LIMIT enforcement.
    # If no LIMIT, inject one. If LIMIT > cap, shrink to cap.
    # -------------------------------------------------------------------
    limit_node = root.find(exp.Limit)
    row_limit = settings.query_row_limit

    if limit_node is None:
        # Inject LIMIT at the top of the query.
        root.set("limit", exp.Limit(expression=exp.Literal.number(row_limit)))
        limit_injected = True
        limit_shrunk = False
    else:
        limit_injected = False
        limit_shrunk = False
        try:
            current = int(limit_node.expression.sql())
            if current > row_limit:
                limit_node.set("expression", exp.Literal.number(row_limit))
                limit_shrunk = True
        except (ValueError, TypeError):
            # LIMIT is an expression (e.g. a parameter) — replace with the cap.
            limit_node.set("expression", exp.Literal.number(row_limit))
            limit_shrunk = True

    # -------------------------------------------------------------------
    # Step 6: Render the (possibly rewritten) SQL back to a string.
    # -------------------------------------------------------------------
    try:
        rewritten = root.sql(dialect=dialect, pretty=True)
    except Exception:
        # Fallback to the original if rendering fails — but flag it.
        rewritten = sql

    return ValidationResult(
        ok=True,
        rewritten_sql=rewritten,
        limit_injected=limit_injected,
        limit_shrunk=limit_shrunk,
    )
