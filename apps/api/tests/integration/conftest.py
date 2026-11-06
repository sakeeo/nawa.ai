import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from nawa.core.config import get_settings
from nawa.core.db import get_sessionmaker
from nawa.core.ratelimit import get_redis
from nawa.main import create_app
from tests.integration.helpers import Actor, insert_user, log_in

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


@pytest_asyncio.fixture
async def sessionmaker(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def app(
    sessionmaker: async_sessionmaker[AsyncSession],
    database: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FastAPI]:
    monkeypatch.setenv("DATABASE_URL", database["app"])
    monkeypatch.setenv("REDIS_URL", "redis://unused:6379/0")
    monkeypatch.setenv("LOGIN_LIMIT_PER_IP", "10")
    get_settings.cache_clear()
    application = create_app()
    redis = fakeredis.aioredis.FakeRedis()
    application.dependency_overrides[get_sessionmaker] = lambda: sessionmaker
    application.dependency_overrides[get_redis] = lambda: redis
    yield application
    await redis.aclose()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client_factory(app: FastAPI) -> AsyncIterator[Callable[[], httpx.AsyncClient]]:
    clients: list[httpx.AsyncClient] = []

    def make() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest_asyncio.fixture
async def client(client_factory: Callable[[], httpx.AsyncClient]) -> httpx.AsyncClient:
    return client_factory()


@pytest_asyncio.fixture
async def make_actor(
    client_factory: Callable[[], httpx.AsyncClient], owner_engine: AsyncEngine
) -> Callable[..., Awaitable[Actor]]:
    """Create a user directly in the database, log in with a fresh cookie jar, return it."""

    async def make(email: str, *, is_admin: bool = False, is_active: bool = True) -> Actor:
        user_id = await insert_user(owner_engine, email, is_admin=is_admin, is_active=is_active)
        http = client_factory()
        csrf = await log_in(http, email)
        return Actor(user_id=user_id, email=email, client=http, csrf=csrf)

    return make
