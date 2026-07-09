"""
Seed script for the e-commerce schema.

Generates realistic synthetic data with *engineered ground truth* — three
deliberate patterns that make the Week 4 benchmark measurable rather than
guess-driven. See README ("Why synthetic data with engineered patterns")
for the design rationale and how this connects to the Causal Impact
project's ground-truth philosophy.

Engineered patterns
-------------------
1. **North region, 2025-Q3**: ~45% drop in repeat-customer probability
   relative to baseline.
   -> Benchmark question "Which region had the biggest drop in repeat
      customers last quarter?" has a known, unambiguous answer.

2. **West region, 2024-Q4 -> 2025-Q1**: ~65% lift in repeat-customer
   probability (holiday-acquisition cohort coming back).
   -> Benchmark question about growth signals has a known answer.

3. **Central region, all 2025**: deliberately flat repeat-customer rate
   (within +/-2% Q-over-Q). Other regions fluctuate naturally.
   -> Benchmark questions like "Did any region have a *significant*
      change in repeat customers in 2025?" have the honest answer
      "Central was flat" — this tests that the system does NOT overclaim
      a pattern that isn't there.

Reproducibility
---------------
Faker is seeded with a fixed value so re-running the seed produces
byte-identical data. This matters for the benchmark — without a fixed
seed, Week 4's accuracy numbers couldn't be reproduced.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta

from faker import Faker
from sqlalchemy import text, bindparam

from app.db import engine
from scripts.init_db import init_db


# ---------------------------------------------------------------------------
# Reproducibility — fixed seed everywhere.
# ---------------------------------------------------------------------------
SEED = 42
fake = Faker("en_US")
Faker.seed(SEED)
random.seed(SEED)


# ---------------------------------------------------------------------------
# Configuration — tunable parameters.
# ---------------------------------------------------------------------------
NUM_REGIONS = 5
NUM_CUSTOMERS = 10_000
NUM_PRODUCTS = 200

# Order date range: 24 months. "Last quarter" in benchmark questions refers
# to the most recent fully-completed quarter.
DATE_END = date(2025, 12, 31)
DATE_START = date(2024, 1, 1)

REGIONS = [
    ("North",   "United States"),
    ("South",   "United States"),
    ("East",    "United States"),
    ("West",    "United States"),
    ("Central", "United States"),
]

# Product categories with realistic price ranges (price low/high).
# Cost is generated as 50-70% of price.
PRODUCT_CATEGORIES = {
    "Electronics": (50, 1500),
    "Clothing":    (15, 200),
    "Home":        (10, 500),
    "Books":       (8, 60),
    "Sports":      (20, 400),
    "Beauty":      (5, 80),
    "Toys":        (10, 150),
}

ORDER_STATUSES = [
    # (status, weight) — matches real e-commerce funnel distribution.
    ("delivered", 70),
    ("shipped",   15),
    ("paid",       5),
    ("cancelled",  5),
    ("returned",   5),
    ("pending",    0),
]
PAYMENT_METHODS = ["credit_card", "debit_card", "paypal", "bank_transfer"]

# Baseline probability that a customer places >=2 orders in any given quarter.
# This is the "repeat rate" the engineered patterns modify.
BASELINE_QUARTERLY_REPEAT_PROB = 0.18

# Engineered multipliers on the baseline repeat probability.
# (region_name, year, quarter) -> multiplier
# Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec
ENGINEERED_PATTERNS: dict[tuple[str, int, int], float] = {
    # Pattern 1: North 2025-Q3 drop.
    ("North",   2025, 3): 0.55,
    # Pattern 2: West holiday-cohort return in 2025-Q1.
    ("West",    2024, 4): 1.10,
    ("West",    2025, 1): 1.65,
    # Pattern 3: Central deliberately flat across all 2025 quarters —
    # pinned to exactly 1.00 with no noise so Q-over-Q variation comes
    # only from Poisson sampling. The honest answer for "did Central
    # change significantly?" is "no".
    ("Central", 2025, 1): 1.00,
    ("Central", 2025, 2): 1.00,
    ("Central", 2025, 3): 1.00,
    ("Central", 2025, 4): 1.00,
}

# Holiday-season weighting: Nov-Dec sees ~2.5x normal order volume.
HOLIDAY_MULTIPLIER = 2.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quarter_of(d: date) -> tuple[int, int]:
    """Return (year, quarter) for a date."""
    return d.year, (d.month - 1) // 3 + 1


def _repeat_prob_for(region_name: str, d: date) -> float:
    """Repeat-customer probability for a (region, date) bucket.

    Central 2025 is *forced* to baseline (multiplier 1.00) with zero noise,
    so its quarter-over-quarter variation comes only from Poisson sampling —
    making "no significant change" the honest statistical answer.
    Other regions get small natural noise on top of any engineered multiplier.
    """
    year, q = _quarter_of(d)
    mult = ENGINEERED_PATTERNS.get((region_name, year, q), 1.0)
    if region_name == "Central" and year == 2025:
        return BASELINE_QUARTERLY_REPEAT_PROB * mult  # no noise
    noise = random.uniform(0.95, 1.05)
    return BASELINE_QUARTERLY_REPEAT_PROB * mult * noise


def _volume_mult_for(region_name: str, d: date) -> float:
    """Order volume multiplier for a (region, date) bucket.

    The holiday multiplier fires when the *quarter* contains Nov-Dec, not when
    the quarter *starts* in Nov-Dec (qstart for Q4 is October 1).
    """
    mult = 1.0
    year, q = _quarter_of(d)
    if q == 4:  # Q4 contains Nov and Dec
        mult *= HOLIDAY_MULTIPLIER
    key = (region_name, year, q)
    if key in ENGINEERED_PATTERNS:
        engineered_mult = ENGINEERED_PATTERNS[key]
        # Dampened effect on volume (the engineered signal is primarily
        # on *repeat rate*, secondarily on volume).
        mult *= (0.5 + 0.5 * engineered_mult)
    return mult


def _product_name_for(category: str, idx: int) -> str:
    adjectives = ["Premium", "Classic", "Pro", "Lite", "Ultra", "Smart", "Eco"]
    return f"{random.choice(adjectives)} {category} Item #{idx:03d}"


def _quarter_iter(start: date, end: date):
    """Yield (year, quarter, qstart, qend) for each quarter in [start, end]."""
    y, q = start.year, (start.month - 1) // 3 + 1
    while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
        qstart = date(y, (q - 1) * 3 + 1, 1)
        if q < 4:
            qend = date(y, q * 3 + 1, 1) - timedelta(days=1)
        else:
            qend = date(y + 1, 1, 1) - timedelta(days=1)
        qend = min(qend, end)
        yield (y, q, qstart, qend)
        q += 1
        if q > 4:
            q = 1
            y += 1


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def seed_regions() -> list[int]:
    """Insert the 5 fixed regions. Returns region_id list in order."""
    ids: list[int] = []
    with engine.begin() as conn:
        for name, country in REGIONS:
            row = conn.execute(
                text("""INSERT INTO regions (region_name, country)
                        VALUES (:name, :country)
                        ON CONFLICT(region_name) DO UPDATE SET country = :country
                        RETURNING region_id"""),
                {"name": name, "country": country},
            ).fetchone()
            ids.append(row[0])
    return ids


def seed_products() -> list[int]:
    """Insert 200 products spread across the 7 categories."""
    product_ids: list[int] = []
    categories = list(PRODUCT_CATEGORIES.keys())
    allocation = [categories[i % len(categories)] for i in range(NUM_PRODUCTS)]
    random.shuffle(allocation)

    with engine.begin() as conn:
        for i, category in enumerate(allocation):
            lo, hi = PRODUCT_CATEGORIES[category]
            price = round(random.uniform(lo, hi), 2)
            cost = round(price * random.uniform(0.50, 0.70), 2)
            name = _product_name_for(category, i)
            sku = f"{category[:3].upper()}-{i:04d}-{random.randint(1000, 9999)}"
            stock = random.randint(0, 500)
            is_active = random.random() > 0.10  # 10% discontinued
            row = conn.execute(
                text("""INSERT INTO products
                        (name, category, sku, price, cost, stock_quantity, is_active)
                        VALUES (:name, :category, :sku, :price, :cost, :stock, :active)
                        ON CONFLICT(sku) DO UPDATE SET name = excluded.name
                        RETURNING product_id"""),
                {"name": name, "category": category, "sku": sku,
                 "price": price, "cost": cost, "stock": stock,
                 "active": is_active},
            ).fetchone()
            product_ids.append(row[0])
    return product_ids


def seed_customers(region_ids: list[int]) -> list[tuple[int, int]]:
    """Insert 10k customers. Returns list of (customer_id, region_id)."""
    customers: list[tuple[int, int]] = []
    # Uneven distribution across regions (realistic).
    weights = [0.22, 0.18, 0.20, 0.25, 0.15]  # North, South, East, West, Central
    region_pool = [region_ids[i] for i in range(len(region_ids))
                   for _ in range(int(weights[i] * 1000))]
    random.shuffle(region_pool)

    # To avoid long-running per-row inserts (which can cause server-side
    # disconnects on managed Postgres), insert customers in chunked batches.
    # Use INSERT ... ON CONFLICT(email) DO UPDATE ... RETURNING customer_id,email
    # so we can obtain the actual assigned customer_id for each email and
    # build the `customers` list reliably (this avoids referencing IDs that
    # were not created because the row conflicted with an existing email).
    chunk = 1000
    rows_buffer: list[dict] = []

    with engine.begin() as conn:
        for i in range(NUM_CUSTOMERS):
            first = fake.first_name()
            last = fake.last_name()
            email = f"{first.lower()}.{last.lower()}{i}@example.com"
            region_id = region_pool[i % len(region_pool)]
            signup = fake.date_between(
                DATE_START - timedelta(days=365),
                DATE_END - timedelta(days=30),
            )
            is_active = random.random() > 0.05

            rows_buffer.append({
                "first_name": first,
                "last_name": last,
                "email": email,
                "region_id": region_id,
                "signup_date": signup,
                "is_active": is_active,
            })

            if len(rows_buffer) >= chunk:
                # map email -> region_id for returned rows
                email_to_region = {r["email"]: r["region_id"] for r in rows_buffer}

                # Try using RETURNING; if the dialect doesn't support it, fall
                # back to inserting then selecting the customer_ids by email.
                try:
                    res = conn.execute(
                        text("""INSERT INTO customers
                                (first_name, last_name, email, region_id, signup_date, is_active)
                                VALUES (:first_name, :last_name, :email, :region_id, :signup_date, :is_active)
                                ON CONFLICT(email) DO UPDATE SET
                                  first_name = excluded.first_name,
                                  last_name = excluded.last_name,
                                  region_id = excluded.region_id,
                                  signup_date = excluded.signup_date,
                                  is_active = excluded.is_active
                                RETURNING customer_id, email"""),
                        rows_buffer,
                    )
                    returned = res.fetchall()
                    for row in returned:
                        cid = row[0]
                        em = row[1]
                        customers.append((cid, email_to_region.get(em)))
                except Exception:
                    conn.execute(
                        text("""INSERT INTO customers
                                (first_name, last_name, email, region_id, signup_date, is_active)
                                VALUES (:first_name, :last_name, :email, :region_id, :signup_date, :is_active)
                                ON CONFLICT(email) DO UPDATE SET
                                  first_name = excluded.first_name,
                                  last_name = excluded.last_name,
                                  region_id = excluded.region_id,
                                  signup_date = excluded.signup_date,
                                  is_active = excluded.is_active"""),
                        rows_buffer,
                    )
                    emails = [r["email"] for r in rows_buffer]
                    # Use an expanding bindparam so IN-list works across dialects.
                    q = text("SELECT customer_id, email FROM customers WHERE email IN :emails").bindparams(bindparam("emails", expanding=True))
                    rows = conn.execute(q, {"emails": emails}).fetchall()
                    for cid, em in rows:
                        customers.append((cid, email_to_region.get(em)))

                rows_buffer.clear()

        # Flush remaining rows
        if rows_buffer:
            email_to_region = {r["email"]: r["region_id"] for r in rows_buffer}
            try:
                res = conn.execute(
                    text("""INSERT INTO customers
                            (first_name, last_name, email, region_id, signup_date, is_active)
                            VALUES (:first_name, :last_name, :email, :region_id, :signup_date, :is_active)
                            ON CONFLICT(email) DO UPDATE SET
                              first_name = excluded.first_name,
                              last_name = excluded.last_name,
                              region_id = excluded.region_id,
                              signup_date = excluded.signup_date,
                              is_active = excluded.is_active
                            RETURNING customer_id, email"""),
                    rows_buffer,
                )
                returned = res.fetchall()
                for row in returned:
                    cid = row[0]
                    em = row[1]
                    customers.append((cid, email_to_region.get(em)))
            except Exception:
                conn.execute(
                    text("""INSERT INTO customers
                            (first_name, last_name, email, region_id, signup_date, is_active)
                            VALUES (:first_name, :last_name, :email, :region_id, :signup_date, :is_active)
                            ON CONFLICT(email) DO UPDATE SET
                              first_name = excluded.first_name,
                              last_name = excluded.last_name,
                              region_id = excluded.region_id,
                              signup_date = excluded.signup_date,
                              is_active = excluded.is_active"""),
                    rows_buffer,
                )
                emails = [r["email"] for r in rows_buffer]
                q = text("SELECT customer_id, email FROM customers WHERE email IN :emails").bindparams(bindparam("emails", expanding=True))
                rows = conn.execute(q, {"emails": emails}).fetchall()
                for cid, em in rows:
                    customers.append((cid, email_to_region.get(em)))

    return customers


def seed_orders(customers: list[tuple[int, int]], product_ids: list[int]) -> None:
    """Generate orders with engineered repeat-customer patterns.

    For each (region, quarter) bucket:
      1. Identify customers in that region.
      2. Decide how many of them are "repeat" (>=2 orders this quarter)
         using the engineered repeat probability.
      3. Decide how many total orders to generate (volume multiplier).
      4. Distribute orders: repeat customers get 2-5, one-timers get 1.
    """
    by_region: dict[int, list[int]] = defaultdict(list)
    for cid, rid in customers:
        by_region[rid].append(cid)
    # Map region_id -> region_name (region_id is autoincrement in insertion order).
    region_name_by_id = {i + 1: name for i, (name, _) in enumerate(REGIONS)}

    # Pre-fetch product prices (snapshot source).
    with engine.connect() as conn:
        prices = {row[0]: float(row[1]) for row in conn.execute(
            text("SELECT product_id, price FROM products")
        )}

    order_rows: list[dict] = []
    item_rows: list[dict] = []
    # Start counters after current max ids to make seeding idempotent.
    with engine.connect() as conn:
        max_order = conn.execute(text("SELECT COALESCE(MAX(order_id), 0) FROM orders")).scalar() or 0
        max_item = conn.execute(text("SELECT COALESCE(MAX(order_item_id), 0) FROM order_items")).scalar() or 0
    order_id_counter = int(max_order)
    item_id_counter = int(max_item)

    for y, q, qstart, qend in _quarter_iter(DATE_START, DATE_END):
        for rid, cids in by_region.items():
            rname = region_name_by_id[rid]
            volume_mult = _volume_mult_for(rname, qstart)
            repeat_prob = _repeat_prob_for(rname, qstart)

            # ~30% of all customers place an order in a given quarter (baseline).
            n_active = int(len(cids) * 0.30 * volume_mult)
            n_active = max(1, min(n_active, len(cids)))
            active_this_q = random.sample(cids, n_active)

            n_repeat = int(n_active * repeat_prob)
            n_repeat = min(n_repeat, n_active)
            repeat_set = set(random.sample(active_this_q, n_repeat))
            one_time_set = [c for c in active_this_q if c not in repeat_set]

            # Repeat customers place 2-5 orders in the quarter.
            for cid in repeat_set:
                n_orders = random.randint(2, 5)
                for _ in range(n_orders):
                    order_id_counter += 1
                    order_date = fake.date_time_between(qstart, qend)
                    item_id_counter = _emit_order(
                        order_id_counter, cid, order_date,
                        product_ids, prices,
                        order_rows, item_rows, item_id_counter,
                    )
            for cid in one_time_set:
                order_id_counter += 1
                order_date = fake.date_time_between(qstart, qend)
                item_id_counter = _emit_order(
                    order_id_counter, cid, order_date,
                    product_ids, prices,
                    order_rows, item_rows, item_id_counter,
                )

    print(f"[seed] Generated {len(order_rows):,} orders, {len(item_rows):,} order_items.")
    _bulk_insert_orders(order_rows, item_rows)


def _emit_order(
    order_id: int,
    customer_id: int,
    order_date: datetime,
    product_ids: list[int],
    prices: dict[int, float],
    order_rows: list[dict],
    item_rows: list[dict],
    item_id_counter: int,
) -> int:
    """Build one order (1-5 items) and append to the buffer lists.

    Returns the updated item_id_counter.
    """
    n_items = random.choices([1, 2, 3, 4, 5], weights=[20, 30, 25, 15, 10])[0]
    chosen = random.sample(product_ids, n_items)
    total = 0.0
    for pid in chosen:
        qty = random.randint(1, 3)
        unit = prices[pid]
        total += qty * unit
        item_id_counter += 1
        item_rows.append({
            "order_item_id": item_id_counter,
            "order_id": order_id,
            "product_id": pid,
            "quantity": qty,
            "unit_price": unit,
        })

    status = random.choices(
        [s for s, _ in ORDER_STATUSES],
        weights=[w for _, w in ORDER_STATUSES],
    )[0]
    if status == "pending" and random.random() > 0.2:
        status = "paid"  # promote most pending to paid (realistic)
    payment = random.choice(PAYMENT_METHODS)

    order_rows.append({
        "order_id": order_id,
        "customer_id": customer_id,
        "order_date": order_date,
        "status": status,
        "total_amount": round(total, 2),
        "payment_method": payment,
    })
    return item_id_counter


def _bulk_insert_orders(order_rows: list[dict], item_rows: list[dict]) -> None:
    """Insert generated orders + items in chunks."""
    chunk = 5000
    with engine.begin() as conn:
        # Only SQLite supports PRAGMA foreign_keys; skip for Postgres/others.
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = OFF"))  # bulk-insert speedup
        for i in range(0, len(order_rows), chunk):
            conn.execute(
                text("""INSERT INTO orders
                        (order_id, customer_id, order_date, status, total_amount, payment_method)
                        VALUES (:order_id, :customer_id, :order_date, :status, :total_amount, :payment_method)"""),
                order_rows[i:i + chunk],
            )
        for i in range(0, len(item_rows), chunk):
            conn.execute(
                text("""INSERT INTO order_items
                        (order_item_id, order_id, product_id, quantity, unit_price)
                        VALUES (:order_item_id, :order_id, :product_id, :quantity, :unit_price)"""),
                item_rows[i:i + chunk],
            )
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = ON"))


# ---------------------------------------------------------------------------
# Sanity checks (printed at end of seed)
# ---------------------------------------------------------------------------

def print_summary() -> None:
    """Print row counts + the engineered-pattern verification."""
    with engine.connect() as conn:
        print("\n[seed] Row counts:")
        for table in ["regions", "customers", "products", "orders", "order_items"]:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table:15s} {n:>10,} rows")

        print("\n[verification] Repeat customers by region x quarter (2025):")
        print("  region    | 2025-Q1 | 2025-Q2 | 2025-Q3 | 2025-Q4 | Q2->Q3 delta")
        print("  ----------+---------+---------+---------+---------+-------------")
        for (rname,) in conn.execute(text("SELECT region_name FROM regions ORDER BY region_name")):
            counts = []
            for q in (1, 2, 3, 4):
                qstart = date(2025, (q - 1) * 3 + 1, 1)
                qend = date(2025, q * 3 + 1, 1) - timedelta(days=1) if q < 4 else date(2025, 12, 31)
                sql = """
                    SELECT COUNT(*) FROM (
                        SELECT c.customer_id
                        FROM customers c
                        JOIN orders o ON o.customer_id = c.customer_id
                        JOIN regions r ON r.region_id = c.region_id
                        WHERE r.region_name = :rname
                          AND date(o.order_date) BETWEEN :qs AND :qe
                        GROUP BY c.customer_id
                        HAVING COUNT(o.order_id) >= 2
                    )
                """
                n = conn.execute(text(sql), {"rname": rname, "qs": qstart, "qe": qend}).scalar()
                counts.append(n)
            delta = counts[2] - counts[1]
            marker = ""
            if rname == "North" and delta < 0:
                marker = " <- engineered drop"
            elif rname == "Central":
                marker = " <- engineered flat"
            elif rname == "West" and counts[0] > counts[1] * 1.3:
                marker = " <- engineered growth (Q1)"
            print(f"  {rname:9s} | {counts[0]:>7} | {counts[1]:>7} | {counts[2]:>7} | {counts[3]:>7} | {delta:>+11}{marker}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[seed] Initializing schema (idempotent)...")
    init_db()
    print("[seed] Seeding regions...")
    region_ids = seed_regions()
    print(f"[seed] Seeding {NUM_PRODUCTS} products...")
    product_ids = seed_products()
    print(f"[seed] Seeding {NUM_CUSTOMERS} customers...")
    customers = seed_customers(region_ids)
    print("[seed] Seeding orders with engineered patterns...")
    seed_orders(customers, product_ids)
    print_summary()
    print("\n[seed] Done.")
