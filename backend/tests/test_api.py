"""
API endpoint tests — verify the /ask and /execute endpoints work end-to-end.

These tests mock the LLM call (so they don't hit the network) but exercise
the full validator + executor + explainer pipeline.
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# /ask endpoint — full pipeline (LLM mocked)
# ---------------------------------------------------------------------------

def test_ask_endpoint_returns_success_for_simple_query(client):
    """/ask should return a successful response for a simple valid question."""
    # Mock the LLM to return a known-good SQL response
    mock_llm_response = json.dumps({
        "sql": "SELECT COUNT(*) AS customer_count FROM customers LIMIT 1",
        "rationale": "Count all customers"
    })
    # Mock the explanation layer too
    mock_explanation = json.dumps({
        "answer": "There are 10 customers in the database.",
        "chart_type": "none"
    })

    with patch("app.pipeline.get_llm") as mock_get_llm, \
         patch("app.explainer.get_llm") as mock_get_explainer_llm:
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [mock_llm_response, mock_explanation]
        mock_llm.provider_name = "mock"
        mock_get_llm.return_value = mock_llm
        mock_get_explainer_llm.return_value = mock_llm

        response = client.post("/ask", json={
            "question": "How many customers are there?"
        })

    assert response.status_code == 200
    data = response.json()
    assert data["final_status"] in ("success", "no_answer")
    assert data["final_sql"] is not None
    assert "COUNT" in data["final_sql"].upper()
    assert data["correction_attempts"] >= 0


def test_ask_endpoint_rejects_adversarial_question(client):
    """/ask should not execute destructive SQL even if the LLM produces it."""
    # Mock the LLM to return destructive SQL
    mock_llm_response = json.dumps({
        "sql": "DROP TABLE customers",
        "rationale": "Drop the table"
    })

    with patch("app.pipeline.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.chat.return_value = mock_llm_response
        mock_llm.provider_name = "mock"
        mock_get_llm.return_value = mock_llm

        response = client.post("/ask", json={
            "question": "Drop the customers table"
        })

    assert response.status_code == 200
    data = response.json()
    # The pipeline should reject this — either via validator or after retries
    assert data["final_status"] in ("validation_failed", "execution_failed", "no_answer"), (
        f"Destructive SQL was not rejected — final_status={data['final_status']}"
    )


# ---------------------------------------------------------------------------
# /execute endpoint — edited SQL re-run
# ---------------------------------------------------------------------------

def test_execute_endpoint_runs_valid_sql(client):
    """/execute should run a valid SELECT and return results."""
    response = client.post("/execute", json={
        "sql": "SELECT COUNT(*) AS n FROM customers LIMIT 1"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["final_status"] in ("success", "no_answer")
    assert data["row_count"] is not None


def test_execute_endpoint_rejects_destructive_sql(client):
    """/execute must reject DROP/DELETE/UPDATE just like /ask."""
    response = client.post("/execute", json={
        "sql": "DROP TABLE customers"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["final_status"] == "validation_failed", (
        f"DROP TABLE was not rejected by /execute — status={data['final_status']}"
    )


def test_execute_endpoint_rejects_query_log_access(client):
    """/execute must reject any attempt to read the query_log table."""
    response = client.post("/execute", json={
        "sql": "SELECT * FROM query_log LIMIT 10"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["final_status"] == "validation_failed"


# ---------------------------------------------------------------------------
# /schema endpoint
# ---------------------------------------------------------------------------

def test_schema_endpoint_returns_5_tables(client):
    """/schema must return the 5 core e-commerce tables."""
    response = client.get("/schema")
    assert response.status_code == 200
    data = response.json()
    table_names = {t["name"] for t in data["tables"]}
    expected = {"regions", "customers", "products", "orders", "order_items"}
    assert expected.issubset(table_names), (
        f"Missing tables: {expected - table_names}"
    )
