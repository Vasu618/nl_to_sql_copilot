"""
Database initialization — DDL for the e-commerce schema.

This is the *single source of truth* for the schema. The Week 2 schema-context
builder reads live metadata from the DB, so whatever is created here is what
the LLM (and the validator) will see.

Design rules (from docs/architecture.md and the user's confirmed Step 2 design):
- 5 tables exactly: regions, customers, products, orders, order_items
- Region lives on `customers` only (v1 simplification; documented limitation
  in README — stretch goal: add nullable shipping_region_id on orders).
- order_items.unit_price is a snapshot at order time (no separate price-history
  table; matches how real e-commerce systems record historical prices).
- orders.total_amount is denormalized but enforced at seed time.
- Indexes target the actual query patterns of the benchmark questions:
  date-range filters, region-based aggregations, FK joins.

The DDL is written in a SQLite/Postgres portable subset. When migrating to
Postgres for production, the only change needed is swapping INTEGER PRIMARY KEY
AUTOINCREMENT for SERIAL/BIGSERIAL — both are auto-incrementing.
"""
from __future__ import annotations

from sqlalchemy import text

from app.db import engine


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    text,
)

metadata = MetaData()

regions = Table(
    "regions",
    metadata,
    Column("region_id", Integer, primary_key=True, autoincrement=True),
    Column("region_name", String(50), nullable=False, unique=True),
    Column("country", String(50), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

customers = Table(
    "customers",
    metadata,
    Column("customer_id", Integer, primary_key=True, autoincrement=True),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=False),
    Column("email", String(255), nullable=False, unique=True),
    Column("region_id", Integer, ForeignKey("regions.region_id"), nullable=False),
    Column("signup_date", Date, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("TRUE")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
)

products = Table(
    "products",
    metadata,
    Column("product_id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False),
    Column("category", String(50), nullable=False),
    Column("sku", String(50), nullable=False, unique=True),
    Column("price", Numeric(10, 2), nullable=False),
    Column("cost", Numeric(10, 2), nullable=False),
    Column("stock_quantity", Integer, nullable=False, server_default=text("0")),
    Column("is_active", Boolean, nullable=False, server_default=text("TRUE")),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("price > 0", name="chk_products_price_positive"),
    CheckConstraint("cost >= 0", name="chk_products_cost_nonnegative"),
)

orders = Table(
    "orders",
    metadata,
    Column("order_id", Integer, primary_key=True, autoincrement=True),
    Column("customer_id", Integer, ForeignKey("customers.customer_id"), nullable=False),
    Column("order_date", DateTime, nullable=False),
    Column("status", String(20), nullable=False),
    Column("total_amount", Numeric(10, 2), nullable=False),
    Column("payment_method", String(20), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('pending','paid','shipped','delivered','cancelled','returned')",
        name="chk_orders_status",
    ),
    CheckConstraint("total_amount >= 0", name="chk_orders_total_amount_nonnegative"),
    CheckConstraint(
        "payment_method IN ('credit_card','debit_card','paypal','bank_transfer')",
        name="chk_orders_payment_method",
    ),
)

order_items = Table(
    "order_items",
    metadata,
    Column("order_item_id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, ForeignKey("orders.order_id"), nullable=False),
    Column("product_id", Integer, ForeignKey("products.product_id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("quantity > 0", name="chk_order_items_quantity_positive"),
    CheckConstraint("unit_price > 0", name="chk_order_items_unit_price_positive"),
)

# Indexes target the actual benchmark query patterns:
#   - date-range filters ("last quarter")               -> orders.order_date
#   - status filters                                    -> orders.status
#   - region-attributed aggregations                    -> customers.region_id
#   - FK joins (orders<->customers, order_items<->both) -> FK columns
INDEXES = [
    Index("idx_orders_order_date", orders.c.order_date),
    Index("idx_orders_status", orders.c.status),
    Index("idx_orders_customer_id", orders.c.customer_id),
    Index("idx_customers_region_id", customers.c.region_id),
    Index("idx_order_items_order_id", order_items.c.order_id),
    Index("idx_order_items_product_id", order_items.c.product_id),
    Index("idx_products_category", products.c.category),
]


def init_db() -> None:
    """Create all tables and indexes (idempotent)."""
    from app.config import get_settings

    settings = get_settings()
    is_sqlite = settings.database_url.startswith("sqlite")

    if is_sqlite:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))

    metadata.create_all(engine)
    for idx in INDEXES:
        idx.create(engine, checkfirst=True)

    print(f"[init_db] Created {len(metadata.tables)} tables, {len(INDEXES)} indexes.")


if __name__ == "__main__":
    init_db()
