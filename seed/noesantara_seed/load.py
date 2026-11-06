import asyncio

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
