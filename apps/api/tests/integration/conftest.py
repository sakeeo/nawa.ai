import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

API_ROOT = Path(__file__).resolve().parents[2]
APP_ROLE = "nawa_app_test"
APP_PASSWORD = "test-app-password"


@pytest.fixture(scope="session")
def database() -> Iterator[dict[str, str]]:
    """Create a scratch database, migrate it as owner, and drop it afterwards."""
    owner_url = os.environ.get("TEST_DATABASE_OWNER_URL")
    if not owner_url:
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_OWNER_URL must be set in CI")
        pytest.skip("TEST_DATABASE_OWNER_URL not set")
    name = f"nawa_test_{secrets.token_hex(4)}"
    base = make_url(owner_url)

    async def admin(sql: str) -> None:
        engine = create_async_engine(base, isolation_level="AUTOCOMMIT", poolclass=NullPool)
        async with engine.connect() as conn:
            await conn.execute(text(sql))
        await engine.dispose()

    owner_db = base.set(database=name).render_as_string(hide_password=False)
    app_db = base.set(database=name, username=APP_ROLE, password=APP_PASSWORD).render_as_string(
        hide_password=False
    )
    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("POSTGRES_APP_USER", APP_ROLE)
            patch.setenv("POSTGRES_APP_PASSWORD", APP_PASSWORD)
            config = Config(str(API_ROOT / "alembic.ini"))
            config.set_main_option("sqlalchemy.url", owner_db.replace("%", "%%"))
            command.upgrade(config, "head")
        yield {"owner": owner_db, "app": app_db}
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        asyncio.run(admin(f"DROP ROLE IF EXISTS {APP_ROLE}"))


@pytest_asyncio.fixture
async def owner_engine(database: dict[str, str]) -> AsyncIterator[AsyncEngine]:
    """Owner connection. Cleans all data first so every test starts empty."""
    engine = create_async_engine(database["owner"], poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE users, workspaces, memberships, invites, refresh_tokens, audit_logs"
                " RESTART IDENTITY CASCADE"
            )
        )
        await conn.execute(
            text(
                "UPDATE instance_settings SET setup_completed = false, setup_token_hash = NULL,"
                " ai_provider = NULL, demo_data_requested = false"
            )
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def app_engine(
    database: dict[str, str], owner_engine: AsyncEngine
) -> AsyncIterator[AsyncEngine]:
    """Connection as the restricted app role. This is what RLS is enforced against."""
    engine = create_async_engine(database["app"], poolclass=NullPool)
    yield engine
    await engine.dispose()
