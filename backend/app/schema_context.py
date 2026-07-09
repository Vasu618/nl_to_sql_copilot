"""
Schema Context Builder (Week 2 — full version).

Pulls live schema metadata (tables, columns, types, FKs, sample rows) PLUS
runtime context (data date range, row counts) and renders it all into a
single system-prompt-friendly string.

The non-negotiable design rule (from architecture.md §3.3): the LLM never
has to guess column names. Every reference the LLM produces must be
cross-checkable against this exact metadata — that's how the validator
catches hallucinations before execution.

Why include date range + row counts:
- The Week 1 checkpoint exposed a real failure mode: the LLM picked Q4 2023
  vs Q1 2024 as "last quarter" but our data starts 2024-01-01, so Q4 2023
  has zero rows. Telling the LLM the data range upfront prevents this.
- Row counts help the LLM calibrate LIMIT clauses — a question about "all
  regions" should not have LIMIT 1000 when there are only 5 regions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .db import engine_readonly


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool
    foreign_key: str | None  # "ref_table.ref_col" or None


@dataclass
class TableInfo:
    name: str
    row_count: int = 0
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[dict] = field(default_factory=list)
    date_range: tuple[str, str] | None = None  # only for tables with a TIMESTAMP/DATE col


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

# Columns treated as "date columns" for the date-range summary.
# These names are conventional; we also fall back to type detection.
DATE_COLUMN_HINTS = ("order_date", "signup_date", "created_at")


def _is_date_column(col_name: str, col_type: str) -> bool:
    """Heuristic: identify columns that represent dates/timestamps."""
    name_lower = col_name.lower()
    type_lower = col_type.lower()
    if any(h in name_lower for h in DATE_COLUMN_HINTS):
        return True
    return "date" in type_lower or "timestamp" in type_lower


def _serialize_value(v: Any) -> Any:
    """Make a SQL value JSON-serializable (datetime/date/Decimal → str)."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return "<bytes>"
    return v


def _get_row_count(conn: Connection, table_name: str) -> int:
    """Get approximate row count. SQLite doesn't maintain live counts in
    metadata, so we fall back to COUNT(*). For Postgres, pg_class.reltuples
    would be faster but COUNT(*) is fine at our scale (~150k rows)."""
    try:
        return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0)
    except Exception:
        return 0


def _get_date_range(conn: Connection, table_name: str, col_name: str) -> tuple[str, str] | None:
    """Get min/max for a date column. Returns None if unavailable."""
    try:
        result = conn.execute(text(
            f'SELECT MIN("{col_name}"), MAX("{col_name}") FROM "{table_name}"'
        )).fetchone()
        if result and result[0] is not None and result[1] is not None:
            return (str(result[0]), str(result[1]))
    except Exception:
        pass
    return None


def get_schema() -> list[TableInfo]:
    """Return live schema metadata for all tables in the database.

    Uses SQLAlchemy's inspector so it works on both SQLite and Postgres
    without code changes. Reads from the read-only engine (defense in depth:
    even metadata reads go through the read-only role).
    """
    inspector = inspect(engine_readonly)
    tables: list[TableInfo] = []

    with engine_readonly.connect() as conn:
        for table_name in inspector.get_table_names():
            # Skip internal SQLAlchemy migration tables if present.
            if table_name.startswith("sql_") or table_name.startswith("alembic"):
                continue
            # CRITICAL: hide the evaluation log table from the LLM. The LLM
            # must never generate SQL against query_log — that would let it
            # read its own past failures or tamper with benchmark data.
            # The query_log table is for instrumentation only.
            if table_name == "query_log":
                continue

            tinfo = TableInfo(name=table_name)
            tinfo.row_count = _get_row_count(conn, table_name)

            # Build column info + FK map.
            fk_map: dict[str, str] = {}
            for fk in inspector.get_foreign_keys(table_name):
                for constrained_col in fk.get("constrained_columns", []):
                    ref_table = fk["referred_table"]
                    ref_col = fk["referred_columns"][0]
                    fk_map[constrained_col] = f"{ref_table}.{ref_col}"

            pk_cols = set(inspector.get_pk_constraint(table_name)["constrained_columns"])

            for col in inspector.get_columns(table_name):
                col_type = str(col["type"])
                tinfo.columns.append(ColumnInfo(
                    name=col["name"],
                    type=col_type,
                    nullable=col.get("nullable", True),
                    primary_key=col["name"] in pk_cols,
                    foreign_key=fk_map.get(col["name"]),
                ))

                # If this is a date column, capture the range for the prompt.
                if _is_date_column(col["name"], col_type) and tinfo.date_range is None:
                    tinfo.date_range = _get_date_range(conn, table_name, col["name"])

            # 3 sample rows for grounding (e.g., "status" has values 'paid','shipped'...).
            try:
                result = conn.execute(
                    text(f'SELECT * FROM "{table_name}" LIMIT 3')
                )
                tinfo.sample_rows = [
                    {k: _serialize_value(v) for k, v in dict(row._mapping).items()}
                    for row in result
                ]
            except Exception:
                tinfo.sample_rows = []

            tables.append(tinfo)

    # Sort tables in dependency order (regions, customers, products, orders, order_items)
    # so the prompt reads top-down. Simple alpha sort works for our schema.
    tables.sort(key=lambda t: t.name)
    return tables


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def render_schema_for_prompt(tables: list[TableInfo] | None = None) -> str:
    """Render schema as a single string suitable for an LLM system prompt.

    Stays compact — column names, types, FK arrows, sample rows, and per-table
    date ranges. For our 5-table schema this comes out to ~3-4k tokens.
    """
    if tables is None:
        tables = get_schema()

    lines: list[str] = ["DATABASE SCHEMA"]
    lines.append("Format: table_name (row_count) — column_name : type [PK] [NOT NULL] [-> FK ref]")
    lines.append("")

    # FK summary at the top — gives the LLM the join paths at a glance.
    lines.append("Foreign-key relationships (join paths):")
    for t in tables:
        for c in t.columns:
            if c.foreign_key:
                lines.append(f"  {t.name}.{c.name} -> {c.foreign_key}")
    lines.append("")

    # Per-table detail.
    for t in tables:
        header = f"TABLE {t.name} ({t.row_count:,} rows)"
        if t.date_range:
            header += f"  [date range: {t.date_range[0]} to {t.date_range[1]}]"
        lines.append(header)
        for c in t.columns:
            parts = [f"  - {c.name} : {c.type}"]
            if c.primary_key:
                parts.append("[PK]")
            if not c.nullable:
                parts.append("[NOT NULL]")
            if c.foreign_key:
                parts.append(f"-> FK {c.foreign_key}")
            lines.append(" ".join(parts))
        if t.sample_rows:
            lines.append("  sample_rows:")
            for row in t.sample_rows[:3]:
                compact = {
                    k: (str(v)[:50] if v is not None else None)
                    for k, v in row.items()
                }
                lines.append(f"    {compact}")
        lines.append("")

    return "\n".join(lines)


def render_runtime_context() -> str:
    """Render runtime context: today's date, the data's date range, dialect.

    The Week 1 checkpoint exposed that the LLM has no notion of "today"
    relative to the data. Including this in every prompt prevents the
    model from picking arbitrary dates.
    """
    from .config import get_settings
    settings = get_settings()

    dialect = "sqlite" if settings.database_url.startswith("sqlite") else "postgres"

    lines = [
        "RUNTIME CONTEXT",
        f"- Today's date: {date.today().isoformat()}",
        f"- Database dialect: {dialect}  (use {dialect}-compatible SQL only — "
        "no Postgres-only DATE_TRUNC/INTERVAL syntax when on SQLite)",
        f"- 'Last quarter' refers to the most recent fully-completed calendar quarter "
        f"before today. 'Last month' = the calendar month before today.",
        f"- Hard LIMIT cap: {settings.query_row_limit} rows. The validator will "
        "shrink any larger LIMIT you specify. Always include a LIMIT clause.",
        f"- Query execution timeout: {settings.query_timeout_seconds}s. Avoid "
        "expensive cross-joins or unindexed full-table scans.",
    ]
    return "\n".join(lines)
