"""
Smoke tests — verify the app starts up, DB is reachable, basic endpoints work.

These run before any deployment. If smoke tests fail, don't deploy.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    """FastAPI test client — makes real HTTP calls to the app in-process."""
    return TestClient(app)


class TestHealthCheck:
    """Verify the app starts and responds."""

    def test_root_returns_ok_status(self, client):
        """GET / must return 200 with status='ok'."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "app" in data
        assert "version" in data

    def test_root_reports_llm_provider(self, client):
        """GET / must report which LLM provider is configured."""
        response = client.get("/")
        data = response.json()
        assert data["llm_provider"] in ("claude", "glm"), (
            f"Unexpected llm_provider: {data['llm_provider']}"
        )


class TestSchemaEndpoint:
    """Verify the schema endpoint returns live DB metadata."""

    def test_schema_returns_200(self, client):
        """GET /schema must return 200."""
        response = client.get("/schema")
        assert response.status_code == 200

    def test_schema_returns_list_of_tables(self, client):
        """GET /schema must return a list of tables."""
        response = client.get("/schema")
        data = response.json()
        assert "tables" in data
        assert isinstance(data["tables"], list)
        assert len(data["tables"]) > 0, "Schema should have at least one table"

    def test_schema_includes_expected_tables(self, client):
        """The 5 core e-commerce tables must be present."""
        data = client.get("/schema").json()
        table_names = {t["name"] for t in data["tables"]}
        expected = {"regions", "customers", "products", "orders", "order_items"}
        missing = expected - table_names
        assert not missing, f"Missing tables: {missing}"

    def test_schema_hides_query_log_table(self, client):
        """The query_log instrumentation table must NOT be exposed to the LLM."""
        data = client.get("/schema").json()
        table_names = {t["name"] for t in data["tables"]}
        assert "query_log" not in table_names, (
            "query_log should be hidden from the LLM schema view"
        )

    def test_each_table_has_columns(self, client):
        """Every table must have at least one column."""
        data = client.get("/schema").json()
        for table in data["tables"]:
            assert len(table["columns"]) > 0, (
                f"Table {table['name']} has no columns"
            )

    def test_each_table_has_sample_rows(self, client):
        """Every table should have sample rows for the LLM prompt."""
        data = client.get("/schema").json()
        for table in data["tables"]:
            assert "sample_rows" in table, (
                f"Table {table['name']} missing sample_rows field"
            )
