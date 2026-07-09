"""
Shared pytest fixtures.

Creates a fresh test database at backend/data/ecommerce.db (the default
location the app expects) with a minimal set of test data. This avoids
the complexity of patching module-level engine bindings.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "data" / "ecommerce.db"


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create a fresh test database with minimal seed data.

    This runs once per test session. It creates the schema (via init_db)
    and inserts just enough rows for tests to work — much smaller than the
    full ~48k-order seed, so tests run in <1 second.
    """
    # Ensure the data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Remove any existing DB to start fresh
    if DB_PATH.exists():
        DB_PATH.unlink()

    # Import after path setup — this picks up the default config
    # (sqlite:///backend/data/ecommerce.db)
    from app.db import engine
    from scripts.init_db import init_db

    # Create the schema
    init_db()

    # Insert minimal test data
    with engine.begin() as conn:
        # 5 regions
        for name in ("North", "South", "East", "West", "Central"):
            conn.execute(text(
                "INSERT INTO regions (region_name, country) VALUES (:n, 'United States')"
            ), {"n": name})

        # 10 customers (2 per region)
        for i in range(10):
            region_id = (i % 5) + 1
            conn.execute(text(
                "INSERT INTO customers (first_name, last_name, email, region_id, signup_date, is_active) "
                "VALUES (:fn, :ln, :email, :rid, '2024-01-01', 1)"
            ), {
                "fn": f"First{i}",
                "ln": f"Last{i}",
                "email": f"user{i}@example.com",
                "rid": region_id,
            })

        # 5 products
        for i in range(5):
            conn.execute(text(
                "INSERT INTO products (name, category, sku, price, cost, stock_quantity, is_active) "
                "VALUES (:name, 'Electronics', :sku, 100.00, 60.00, 50, 1)"
            ), {"name": f"Product {i}", "sku": f"SKU-{i:04d}"})

        # 20 orders
        for i in range(20):
            conn.execute(text(
                "INSERT INTO orders (customer_id, order_date, status, total_amount, payment_method) "
                "VALUES (:cid, '2025-01-15', 'delivered', 100.00, 'credit_card')"
            ), {"cid": (i % 10) + 1})

        # 20 order items
        for i in range(20):
            conn.execute(text(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (:oid, :pid, 2, 100.00)"
            ), {"oid": (i % 20) + 1, "pid": (i % 5) + 1})

    yield

    # Cleanup: remove the test DB
    if DB_PATH.exists():
        DB_PATH.unlink()
