import os
import secrets
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from noesantara_seed import load as seed_load
from sqlalchemy.engine import make_url

ROLE = "nawa_demo_ro_test"
PASSWORD = "ro-test-password"


def _dsn(url: str, **parts: str) -> str:
    return seed_load.to_asyncpg_dsn(
        make_url(url).set(**parts).render_as_string(hide_password=False)
    )


@pytest_asyncio.fixture
async def demo_db() -> AsyncIterator[str]:
    owner_url = os.environ.get("TEST_DATABASE_OWNER_URL")
    if not owner_url:
        pytest.skip("TEST_DATABASE_OWNER_URL not set")
    name = f"nawa_demo_{secrets.token_hex(4)}"
    admin = await asyncpg.connect(_dsn(owner_url))
    await admin.execute(f'CREATE DATABASE "{name}"')
    target_url = make_url(owner_url).set(database=name).render_as_string(hide_password=False)
    try:
        await seed_load.load_async(target_url)
        yield target_url
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f"DROP ROLE IF EXISTS {ROLE}")
        await admin.close()


async def _connect_as_role(target_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(_dsn(target_url, username=ROLE, password=PASSWORD))


async def test_role_can_select_but_not_write(demo_db: str) -> None:
    await seed_load.ensure_readonly_role(demo_db, ROLE, PASSWORD)
    conn = await _connect_as_role(demo_db)
    try:
        assert await conn.fetchval("SELECT count(*) FROM orders") > 0
        for statement in (
            "INSERT INTO outlets (id, name, city) VALUES (999, 'x', 'y')",
            "UPDATE menu_items SET price = 0",
            "DELETE FROM orders",
            "CREATE TABLE evil (id int)",
            "DROP TABLE orders",
        ):
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(statement)
    finally:
        await conn.close()


async def test_role_is_not_privileged_and_defaults_to_read_only(demo_db: str) -> None:
    await seed_load.ensure_readonly_role(demo_db, ROLE, PASSWORD)
    conn = await _connect_as_role(demo_db)
    try:
        flags = await conn.fetchrow(
            "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = $1", ROLE
        )
        assert tuple(flags) == (False, False, False)
        assert await conn.fetchval("SHOW default_transaction_read_only") == "on"
    finally:
        await conn.close()


async def test_calling_twice_is_idempotent_and_updates_the_password(demo_db: str) -> None:
    await seed_load.ensure_readonly_role(demo_db, ROLE, "first-password")
    await seed_load.ensure_readonly_role(demo_db, ROLE, PASSWORD)
    conn = await _connect_as_role(demo_db)
    await conn.close()


async def test_grants_survive_only_after_reapplying_following_a_reload(demo_db: str) -> None:
    await seed_load.ensure_readonly_role(demo_db, ROLE, PASSWORD)
    await seed_load.load_async(demo_db)  # drops and recreates every table
    await seed_load.ensure_readonly_role(demo_db, ROLE, PASSWORD)
    conn = await _connect_as_role(demo_db)
    try:
        assert await conn.fetchval("SELECT count(*) FROM outlets") == 5
    finally:
        await conn.close()


@pytest.mark.parametrize("bad", ["Robert'; DROP ROLE x;--", "UPPER", "1abc", ""])
async def test_role_name_is_validated(bad: str) -> None:
    with pytest.raises(ValueError):
        await seed_load.ensure_readonly_role("postgresql://x/y", bad, PASSWORD)
