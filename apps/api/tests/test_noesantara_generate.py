from noesantara_seed.generate import (
    ANOMALY_MONTH,
    BANDUNG_ID,
    BEEF_INGREDIENT_ID,
    CHANNELS,
    Dataset,
    generate,
)


def _monthly_revenue(ds: Dataset, outlet_id: int, month: int) -> int:
    order_key = {o[0]: (o[1], o[4].month) for o in ds.orders}
    return sum(q * p for _, oid, _, q, p in ds.order_items if order_key[oid] == (outlet_id, month))


def test_generation_is_deterministic() -> None:
    a, b = generate(), generate()
    assert len(a.orders) == len(b.orders)
    assert a.orders[:50] == b.orders[:50]
    assert a.order_items[-50:] == b.order_items[-50:]


def test_shape_matches_spec() -> None:
    ds = generate()
    assert len(ds.outlets) == 5
    assert len(ds.menu_items) == 72
    assert len(ds.ingredients) == 16
    assert len(ds.customers) == 500
    assert {o[3] for o in ds.orders} == set(CHANNELS)
    assert {o[4].year for o in ds.orders} == {2025}
    assert {o[4].month for o in ds.orders} == set(range(1, 13))


def test_bandung_august_drops_about_30_percent() -> None:
    ds = generate()
    for outlet_id, _, _ in ds.outlets:
        around = (
            _monthly_revenue(ds, outlet_id, ANOMALY_MONTH - 1)
            + _monthly_revenue(ds, outlet_id, ANOMALY_MONTH + 1)
        ) / 2
        ratio = _monthly_revenue(ds, outlet_id, ANOMALY_MONTH) / around
        if outlet_id == BANDUNG_ID:
            assert 0.6 <= ratio <= 0.8, ratio
        else:
            assert ratio > 0.85, (outlet_id, ratio)


def test_bandung_beef_out_of_stock_and_beef_dishes_unsold_in_august() -> None:
    ds = generate()
    august = [r for r in ds.ingredient_stock if r[0] == BANDUNG_ID and r[2].month == ANOMALY_MONTH]
    assert {r[1] for r in august if r[3] == 0} == {BEEF_INGREDIENT_ID}

    beef_dishes = {r[0] for r in ds.recipes if r[1] == BEEF_INGREDIENT_ID}
    assert beef_dishes == set(range(1, 13))
    bandung_august = {o[0] for o in ds.orders if o[1] == BANDUNG_ID and o[4].month == ANOMALY_MONTH}
    sold = {i[2] for i in ds.order_items if i[1] in bandung_august}
    assert not sold & beef_dishes
