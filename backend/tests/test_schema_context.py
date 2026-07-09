"""
Schema context builder tests — verify the runtime schema discovery works
correctly and produces LLM-friendly output.
"""
from __future__ import annotations

import pytest

from app.schema_context import (
    get_schema,
    render_schema_for_prompt,
    render_runtime_context,
)


@pytest.fixture(scope="module")
def schema_tables():
    return get_schema()


class TestSchemaDiscovery:
    """Verify the schema is discovered correctly from the live DB."""

    def test_get_schema_returns_list(self, schema_tables):
        assert isinstance(schema_tables, list)
        assert len(schema_tables) > 0

    def test_each_table_has_name(self, schema_tables):
        for t in schema_tables:
            assert t.name, "Table missing name"

    def test_each_table_has_columns(self, schema_tables):
        for t in schema_tables:
            assert len(t.columns) > 0, f"Table {t.name} has no columns"

    def test_each_column_has_required_fields(self, schema_tables):
        for t in schema_tables:
            for col in t.columns:
                assert col.name, f"Column in {t.name} missing name"
                assert col.type, f"Column {t.name}.{col.name} missing type"
                assert isinstance(col.nullable, bool)
                assert isinstance(col.primary_key, bool)

    def test_customers_table_has_expected_columns(self, schema_tables):
        customers = next(t for t in schema_tables if t.name == "customers")
        col_names = {c.name for c in customers.columns}
        expected = {"customer_id", "first_name", "last_name", "email",
                    "region_id", "signup_date", "is_active", "created_at"}
        assert expected.issubset(col_names), (
            f"Missing columns: {expected - col_names}"
        )

    def test_fk_relationships_are_detected(self, schema_tables):
        """The customers.region_id column should have an FK to regions.region_id."""
        customers = next(t for t in schema_tables if t.name == "customers")
        region_id_col = next(c for c in customers.columns if c.name == "region_id")
        assert region_id_col.foreign_key == "regions.region_id", (
            f"FK not detected: {region_id_col.foreign_key}"
        )

    def test_query_log_is_hidden(self, schema_tables):
        """query_log must NOT appear in the schema (hidden from LLM)."""
        names = {t.name for t in schema_tables}
        assert "query_log" not in names


class TestSchemaRendering:
    """Verify the schema renders to a prompt-friendly string."""

    def test_render_schema_returns_non_empty_string(self, schema_tables):
        rendered = render_schema_for_prompt(schema_tables)
        assert isinstance(rendered, str)
        assert len(rendered) > 100, "Schema render too short"
        assert "DATABASE SCHEMA" in rendered

    def test_render_schema_includes_all_table_names(self, schema_tables):
        rendered = render_schema_for_prompt(schema_tables)
        for t in schema_tables:
            assert t.name in rendered, f"Table {t.name} not in rendered schema"

    def test_render_runtime_context_includes_today_date(self):
        ctx = render_runtime_context()
        assert "Today's date" in ctx
        assert "dialect" in ctx.lower()
