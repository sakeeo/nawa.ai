"""Deterministic synthetic data for Resto Noesantara (fictional restaurant chain).

Planted anomaly: in August, the beef supplier fails to deliver to Bandung (outlet 2), so
beef is out of stock, every beef dish is unavailable, and the outlet's sales drop by
about 30%.
"""

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

OUTLETS = [
    (1, "Jakarta Selatan", "Jakarta"),
    (2, "Bandung", "Bandung"),
    (3, "Surabaya", "Surabaya"),
    (4, "Yogyakarta", "Yogyakarta"),
    (5, "Medan", "Medan"),
]
# category: (min price, max price, main ingredient ids)
MENU_CATEGORIES = {
    "Olahan Sapi": (45_000, 120_000, (1,)),
    "Olahan Ayam": (30_000, 75_000, (2,)),
    "Seafood": (40_000, 150_000, (3, 4)),
    "Sayur & Lauk": (15_000, 45_000, (9,)),
    "Minuman": (8_000, 35_000, (11, 12, 13)),
    "Dessert": (12_000, 40_000, (10, 13, 15)),
}
ITEMS_PER_CATEGORY = 12
INGREDIENTS = [
    (1, "Daging Sapi", "kg"),
    (2, "Ayam", "kg"),
    (3, "Udang", "kg"),
    (4, "Ikan Kakap", "kg"),
    (5, "Beras", "kg"),
    (6, "Santan", "liter"),
    (7, "Cabai Merah", "kg"),
    (8, "Bawang Merah", "kg"),
    (9, "Sayuran Hijau", "kg"),
    (10, "Gula Aren", "kg"),
    (11, "Kopi", "kg"),
    (12, "Teh", "kg"),
    (13, "Susu", "liter"),
    (14, "Minyak Goreng", "liter"),
    (15, "Tepung Terigu", "kg"),
    (16, "Telur", "kg"),
]
SIDE_INGREDIENT_IDS = (5, 6, 7, 8, 14, 16)
CHANNELS = ("dine_in", "takeaway", "delivery")
EXPENSE_CATEGORIES = {
    "Sewa": (35_000_000, 55_000_000),
    "Gaji": (80_000_000, 120_000_000),
    "Listrik, Air & Gas": (10_000_000, 18_000_000),
    "Komisi Delivery": (8_000_000, 15_000_000),
    "Pemasaran": (3_000_000, 8_000_000),
}
BANDUNG_ID = 2
ANOMALY_MONTH = 8
BEEF_INGREDIENT_ID = 1
# Applied to the order count. Revenue falls further because cheaper dishes replace beef.
ANOMALY_FACTOR = 0.8
MIN_STOCK = 20


@dataclass(frozen=True)
class Dataset:
    outlets: list[tuple[int, str, str]]
    menu_items: list[tuple[int, str, str, int, int]]  # id, name, category, food_cost, price
    ingredients: list[tuple[int, str, str]]  # id, name, unit
    recipes: list[tuple[int, int, Decimal]]  # menu_item_id, ingredient_id, qty per portion
    customers: list[tuple[int, str, int]]  # id, name, home outlet_id (loyalty members)
    orders: list[tuple[int, int, int, str, datetime]]  # id, outlet_id, customer_id, channel, at
    order_items: list[tuple[int, int, int, int, int]]  # id, order_id, menu_item_id, qty, price
    ingredient_stock: list[tuple[int, int, date, int, int]]  # outlet, ingredient, month, qty, min
    expenses: list[tuple[int, int, date, str, int]]  # id, outlet_id, month, category, amount


def _is_anomaly(outlet_id: int, month: int) -> bool:
    return outlet_id == BANDUNG_ID and month == ANOMALY_MONTH


def generate(seed: int = 42, year: int = 2025) -> Dataset:
    rng = random.Random(seed)  # noqa: S311 - synthetic demo data, not security

    menu_items: list[tuple[int, str, str, int, int]] = []
    recipes: list[tuple[int, int, Decimal]] = []
    for category, (low, high, main_ids) in MENU_CATEGORIES.items():
        for i in range(1, ITEMS_PER_CATEGORY + 1):
            item_id = len(menu_items) + 1
            price = rng.randrange(low, high, 1_000)
            food_cost = int(price * rng.uniform(0.30, 0.40))
            menu_items.append((item_id, f"{category} {i:02d}", category, food_cost, price))
            main_qty = Decimal(rng.randrange(100, 251, 10)) / 1000
            recipes.append((item_id, rng.choice(main_ids), main_qty))
            for side in rng.sample(SIDE_INGREDIENT_IDS, rng.randint(1, 3)):
                recipes.append((item_id, side, Decimal(rng.randrange(10, 101, 5)) / 1000))
    beef_dish_ids = {r[0] for r in recipes if r[1] == BEEF_INGREDIENT_ID}
    available_without_beef = [m for m in menu_items if m[0] not in beef_dish_ids]

    customers = [(cid, f"Member {cid:04d}", rng.choice(OUTLETS)[0]) for cid in range(1, 501)]
    customers_by_outlet = {o[0]: [c[0] for c in customers if c[2] == o[0]] for o in OUTLETS}

    orders: list[tuple[int, int, int, str, datetime]] = []
    items: list[tuple[int, int, int, int, int]] = []
    day = date(year, 1, 1)
    while day.year == year:
        for outlet_id, _, _ in OUTLETS:
            count = rng.randint(25, 40)
            if _is_anomaly(outlet_id, day.month):
                count = round(count * ANOMALY_FACTOR)
            for _ in range(count):
                order_id = len(orders) + 1
                created = datetime.combine(day, time(rng.randint(10, 21), rng.randint(0, 59)))
                channel = rng.choices(CHANNELS, weights=(6, 1, 3))[0]
                customer_id = rng.choice(customers_by_outlet[outlet_id])
                orders.append((order_id, outlet_id, customer_id, channel, created))
                for _ in range(rng.randint(1, 4)):
                    item = rng.choice(menu_items)
                    if _is_anomaly(outlet_id, day.month) and item[0] in beef_dish_ids:
                        item = rng.choice(available_without_beef)
                    items.append((len(items) + 1, order_id, item[0], rng.randint(1, 3), item[4]))
        day += timedelta(days=1)

    ingredient_stock: list[tuple[int, int, date, int, int]] = []
    expenses: list[tuple[int, int, date, str, int]] = []
    for month in range(1, 13):
        first = date(year, month, 1)
        for outlet_id, _, _ in OUTLETS:
            for ingredient_id, _, _ in INGREDIENTS:
                stock = rng.randint(30, 150)
                if _is_anomaly(outlet_id, month) and ingredient_id == BEEF_INGREDIENT_ID:
                    stock = 0
                ingredient_stock.append((outlet_id, ingredient_id, first, stock, MIN_STOCK))
            for category, (low, high) in EXPENSE_CATEGORIES.items():
                amount = rng.randrange(low, high, 100_000)
                expenses.append((len(expenses) + 1, outlet_id, first, category, amount))

    return Dataset(
        outlets=list(OUTLETS),
        menu_items=menu_items,
        ingredients=list(INGREDIENTS),
        recipes=recipes,
        customers=customers,
        orders=orders,
        order_items=items,
        ingredient_stock=ingredient_stock,
        expenses=expenses,
    )
