import asyncio
import secrets

import asyncpg
from noesantara_seed.load import load, to_asyncpg_dsn
from sqlalchemy.engine import make_url


def test_load_creates_tables_and_is_idempotent(database: dict[str, str]) -> None:
    """Uses a scratch database next to the app test database; dropped afterwards."""
    base = make_url(database["owner"])
    name = f"noesantara_test_{secrets.token_hex(4)}"
    admin_dsn = to_asyncpg_dsn(base.set(database="postgres").render_as_string(hide_password=False))
    target = base.set(database=name).render_as_string(hide_password=False)

    async def run_sql(dsn: str, sql: str) -> list[asyncpg.Record]:
        conn = await asyncpg.connect(dsn)
        try:
            return await conn.fetch(sql)
        finally:
            await conn.close()

    asyncio.run(run_sql(admin_dsn, f'CREATE DATABASE "{name}"'))
    try:
        first = load(target)
        second = load(target)
        assert first == second
        dsn = to_asyncpg_dsn(target)
        orders = asyncio.run(run_sql(dsn, "SELECT count(*) AS n FROM orders"))
        zero = asyncio.run(
            run_sql(
                dsn,
                "SELECT ingredient_id FROM ingredient_stock WHERE outlet_id = 2"
                " AND month = DATE '2025-08-01' AND stock_qty = 0",
            )
        )
        assert orders[0]["n"] == first["orders"]
        assert [r["ingredient_id"] for r in zero] == [1]
    finally:
        asyncio.run(run_sql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


async def test_load_demo_data_creates_the_database_and_loads_it(
    database: dict[str, str],
) -> None:
    from nawa.core.config import Settings
    from nawa.workspace.demo import load_demo_data

    name = f"noesantara_demo_{secrets.token_hex(4)}"
    base = make_url(database["owner"])
    admin_dsn = to_asyncpg_dsn(base.set(database="postgres").render_as_string(hide_password=False))
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        database_owner_url=database["owner"],
        demo_database_name=name,
    )
    try:
        assert await load_demo_data(settings) is True
        target = to_asyncpg_dsn(base.set(database=name).render_as_string(hide_password=False))
        conn = await asyncpg.connect(target)
        try:
            assert await conn.fetchval("SELECT count(*) FROM outlets") == 5
        finally:
            await conn.close()
    finally:
        conn = await asyncpg.connect(admin_dsn)
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.close()
