import asyncio
import re

import asyncpg

from noesantara_seed.generate import generate

DDL = """
DROP TABLE IF EXISTS order_items, orders, ingredient_stock, recipes, expenses, customers,
  ingredients, menu_items, outlets CASCADE;
CREATE TABLE outlets (id int PRIMARY KEY, name text NOT NULL, city text NOT NULL);
CREATE TABLE menu_items (
  id int PRIMARY KEY, name text NOT NULL, category text NOT NULL,
  food_cost bigint NOT NULL, price bigint NOT NULL
);
CREATE TABLE ingredients (id int PRIMARY KEY, name text NOT NULL, unit text NOT NULL);
CREATE TABLE recipes (
  menu_item_id int NOT NULL REFERENCES menu_items(id),
  ingredient_id int NOT NULL REFERENCES ingredients(id),
  quantity numeric(6, 3) NOT NULL,
  PRIMARY KEY (menu_item_id, ingredient_id)
);
CREATE TABLE customers (
  id int PRIMARY KEY, name text NOT NULL, outlet_id int NOT NULL REFERENCES outlets(id)
);
CREATE TABLE orders (
  id int PRIMARY KEY, outlet_id int NOT NULL REFERENCES outlets(id),
  customer_id int NOT NULL REFERENCES customers(id),
  channel text NOT NULL CHECK (channel IN ('dine_in', 'takeaway', 'delivery')),
  created_at timestamp NOT NULL
);
CREATE TABLE order_items (
  id int PRIMARY KEY, order_id int NOT NULL REFERENCES orders(id),
  menu_item_id int NOT NULL REFERENCES menu_items(id), quantity int NOT NULL,
  unit_price bigint NOT NULL
);
CREATE TABLE ingredient_stock (
  outlet_id int NOT NULL REFERENCES outlets(id),
  ingredient_id int NOT NULL REFERENCES ingredients(id),
  month date NOT NULL, stock_qty int NOT NULL, min_stock int NOT NULL,
  PRIMARY KEY (outlet_id, ingredient_id, month)
);
CREATE TABLE expenses (
  id int PRIMARY KEY, outlet_id int NOT NULL REFERENCES outlets(id), month date NOT NULL,
  category text NOT NULL, amount bigint NOT NULL
);
CREATE INDEX orders_outlet_created_idx ON orders (outlet_id, created_at);
CREATE INDEX order_items_order_idx ON order_items (order_id);
"""

TABLES: list[tuple[str, list[str]]] = [
    ("outlets", ["id", "name", "city"]),
    ("menu_items", ["id", "name", "category", "food_cost", "price"]),
    ("ingredients", ["id", "name", "unit"]),
    ("recipes", ["menu_item_id", "ingredient_id", "quantity"]),
    ("customers", ["id", "name", "outlet_id"]),
    ("orders", ["id", "outlet_id", "customer_id", "channel", "created_at"]),
    ("order_items", ["id", "order_id", "menu_item_id", "quantity", "unit_price"]),
    ("ingredient_stock", ["outlet_id", "ingredient_id", "month", "stock_qty", "min_stock"]),
    ("expenses", ["id", "outlet_id", "month", "category", "amount"]),
]


def to_asyncpg_dsn(url: str) -> str:
    """Accept SQLAlchemy-style URLs (postgresql+asyncpg://, postgresql+psycopg://)."""
    scheme, sep, rest = url.partition("://")
    return f"{scheme.split('+', 1)[0]}{sep}{rest}"


async def load_async(url: str, seed: int = 42) -> dict[str, int]:
    dataset = generate(seed)
    counts: dict[str, int] = {}
    conn = await asyncpg.connect(to_asyncpg_dsn(url))
    try:
        async with conn.transaction():
            await conn.execute(DDL)
            for table, columns in TABLES:
                rows = getattr(dataset, table)
                await conn.copy_records_to_table(table, records=rows, columns=columns)
                counts[table] = len(rows)
    finally:
        await conn.close()
    return counts


def load(url: str, seed: int = 42) -> dict[str, int]:
    """Drop and recreate the demo tables, then bulk-load them. Safe to run twice."""
    return asyncio.run(load_async(url, seed))


_DB_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def validate_database_name(name: str) -> str:
    if not _DB_NAME.match(name):
        raise ValueError(f"Invalid database name: {name!r}")
    return name


async def ensure_database(admin_url: str, name: str) -> None:
    """Create the demo database when it does not exist yet. Needs CREATEDB rights."""
    validate_database_name(name)
    conn = await asyncpg.connect(to_asyncpg_dsn(admin_url))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def validate_role_name(name: str) -> str:
    if not _ROLE_NAME.match(name):
        raise ValueError(f"Invalid role name: {name!r}")
    return name


async def ensure_readonly_role(url: str, role: str, password: str) -> None:
    """Create or refresh a SELECT-only login role on the database `url` points at.

    Run it after every `load_async`: reloading drops the tables and with them the grants.
    Needs owner rights. The password is bound through `format(%L)`, never concatenated.
    """
    validate_role_name(role)
    conn = await asyncpg.connect(to_asyncpg_dsn(url))
    try:
        database = await conn.fetchval("SELECT current_database()")
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
        verb = "ALTER" if exists else "CREATE"
        options = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        statements = [
            await conn.fetchval(
                f"SELECT format('{verb} ROLE %I {options} PASSWORD %L', $1::text, $2::text)",
                role,
                password,
            ),
            await conn.fetchval(
                "SELECT format('REVOKE ALL ON DATABASE %I FROM %I', $1::text, $2::text)",
                database,
                role,
            ),
            await conn.fetchval(
                "SELECT format('GRANT CONNECT ON DATABASE %I TO %I', $1::text, $2::text)",
                database,
                role,
            ),
            await conn.fetchval(
                "SELECT format('ALTER ROLE %I IN DATABASE %I SET default_transaction_read_only"
                " = on', $1::text, $2::text)",
                role,
                database,
            ),
            await conn.fetchval(
                "SELECT format('REVOKE ALL ON SCHEMA public FROM %I', $1::text)", role
            ),
            await conn.fetchval(
                "SELECT format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', $1::text)",
                role,
            ),
            await conn.fetchval(
                "SELECT format('GRANT USAGE ON SCHEMA public TO %I', $1::text)", role
            ),
            await conn.fetchval(
                "SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', $1::text)",
                role,
            ),
        ]
        async with conn.transaction():
            for statement in statements:
                await conn.execute(statement)
    finally:
        await conn.close()
