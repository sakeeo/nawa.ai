import pytest
from sqlalchemy import text

from nawa.data import connector
from nawa.data.connector import ConnectionParams, open_engine
from nawa.data.discovery import discover_schema, snapshot_from_json, snapshot_to_json
from tests.integration.conftest import TargetDb


def _params(target: TargetDb, which: str) -> ConnectionParams:
    value = getattr(target, which)
    assert isinstance(value, ConnectionParams)
    return value


async def test_readonly_role_passes_the_connection_test(target_database: TargetDb) -> None:
    report = await connector.test_connection(_params(target_database, "readonly"))
    assert report.ok is True, report.problems
    assert report.server_version and "PostgreSQL" in report.server_version
    assert report.problems == []


async def test_owner_role_fails_because_it_can_write(target_database: TargetDb) -> None:
    report = await connector.test_connection(_params(target_database, "owner"))
    assert report.ok is False
    joined = " ".join(report.problems).lower()
    assert "superuser" in joined


async def test_write_privilege_on_an_allowlisted_table_fails(target_database: TargetDb) -> None:
    ro = _params(target_database, "readonly")
    async with open_engine(_params(target_database, "owner")) as engine:
        async with engine.begin() as conn:
            await conn.execute(text(f'GRANT INSERT ON orders TO "{ro.username}"'))
    report = await connector.test_connection(ro, tables=["orders"])
    assert report.ok is False
    assert any("orders" in problem for problem in report.problems)
    # Tables outside the checked list are not held against the role.
    assert (await connector.test_connection(ro, tables=["outlets"])).ok is True


async def test_create_privilege_on_a_schema_fails(target_database: TargetDb) -> None:
    ro = _params(target_database, "readonly")
    async with open_engine(_params(target_database, "owner")) as engine:
        async with engine.begin() as conn:
            await conn.execute(text(f'GRANT CREATE ON SCHEMA public TO "{ro.username}"'))
    report = await connector.test_connection(ro)
    assert report.ok is False
    assert any("create" in problem.lower() for problem in report.problems)


async def test_wrong_password_fails_without_leaking_it(target_database: TargetDb) -> None:
    ro = _params(target_database, "readonly")
    bad = ConnectionParams(ro.host, ro.port, ro.database, ro.username, "wrong-pass-123", "prefer")
    report = await connector.test_connection(bad)
    assert report.ok is False
    assert all("wrong-pass-123" not in problem for problem in report.problems)


async def test_discovery_returns_tables_columns_keys_and_estimates(
    target_database: TargetDb,
) -> None:
    async with open_engine(_params(target_database, "readonly")) as engine:
        tables = await discover_schema(engine)
    by_name = {t.name: t for t in tables}
    assert set(by_name) == {"outlets", "orders"}
    orders = by_name["orders"]
    assert [c.name for c in orders.columns] == [
        "id",
        "outlet_id",
        "channel",
        "note",
        "amount",
        "created_at",
    ]
    types = {c.name: c.type for c in orders.columns}
    assert types["id"] == "integer"
    assert types["amount"] == "numeric(12,2)"
    assert types["created_at"] == "timestamp without time zone"
    nullable = {c.name: c.nullable for c in orders.columns}
    assert nullable["note"] is True and nullable["channel"] is False
    assert orders.primary_key == ["id"]
    assert len(orders.foreign_keys) == 1
    fk = orders.foreign_keys[0]
    assert (fk.columns, fk.ref_table, fk.ref_columns) == (["outlet_id"], "outlets", ["id"])
    assert by_name["outlets"].foreign_keys == []
    assert all(t.row_estimate >= 0 for t in tables)


async def test_samples_only_for_enum_like_text_columns(target_database: TargetDb) -> None:
    async with open_engine(_params(target_database, "readonly")) as engine:
        tables = await discover_schema(engine)
    orders = {c.name: c for c in {t.name: t for t in tables}["orders"].columns}
    assert orders["channel"].samples == ["delivery", "dine_in", "takeaway"]
    assert orders["note"].samples == []  # 40 distinct, long values
    assert orders["id"].samples == [] and orders["amount"].samples == []
    outlets = {c.name: c for c in {t.name: t for t in tables}["outlets"].columns}
    assert outlets["city"].samples == ["Bandung", "Jakarta", "Medan"]


async def test_excluded_columns_are_never_sampled(target_database: TargetDb) -> None:
    async with open_engine(_params(target_database, "readonly")) as engine:
        tables = await discover_schema(engine, exclude={("outlets", "city")})
    outlets = {c.name: c for c in {t.name: t for t in tables}["outlets"].columns}
    assert outlets["city"].samples == []
    assert outlets["name"].samples == ["Bandung", "Jakarta", "Medan"]


async def test_snapshot_json_round_trips(target_database: TargetDb) -> None:
    async with open_engine(_params(target_database, "readonly")) as engine:
        tables = await discover_schema(engine)
    data = snapshot_to_json(tables)
    import json

    assert snapshot_from_json(json.loads(json.dumps(data))) == tables


@pytest.mark.parametrize("schema", ["no_such_schema"])
async def test_unknown_schema_gives_no_tables(target_database: TargetDb, schema: str) -> None:
    async with open_engine(_params(target_database, "readonly")) as engine:
        assert await discover_schema(engine, schema=schema) == []


async def test_samples_are_taken_only_where_the_allowlist_permits(
    target_database: TargetDb,
) -> None:
    async with open_engine(_params(target_database, "readonly")) as engine:
        tables = await discover_schema(engine, sample_allow={"outlets": {"id", "name"}})
        nothing = await discover_schema(engine, sample_allow={})
    by_table = {t.name: {c.name: c for c in t.columns} for t in tables}
    assert by_table["outlets"]["name"].samples == ["Bandung", "Jakarta", "Medan"]
    assert by_table["outlets"]["city"].samples == []  # column not allowed
    assert by_table["orders"]["channel"].samples == []  # table not allowed
    assert {t.name for t in tables} == {"outlets", "orders"}  # the table list itself is complete
    assert all(not c.samples for t in nothing for c in t.columns)
