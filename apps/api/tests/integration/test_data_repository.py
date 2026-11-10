import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nawa.core.crypto import CredentialVault
from nawa.core.db import apply_rls
from nawa.data import repository
from nawa.data.connector import ConnectionParams, open_engine
from nawa.data.discovery import ColumnInfo, ForeignKey, TableInfo, discover_schema
from nawa.data.schemas import DataSourceCreate, DataSourceRead
from tests.integration.conftest import TargetDb
from tests.integration.helpers import insert_user, insert_workspace

PASSWORD = "very-secret-db-password"


@asynccontextmanager
async def scoped(engine: AsyncEngine, workspace_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await apply_rls(session, workspace_id=workspace_id)
        yield session


def _vault() -> CredentialVault:
    return CredentialVault(Fernet.generate_key().decode())


async def _create(session: AsyncSession, vault: CredentialVault, ws: uuid.UUID, user: uuid.UUID):  # type: ignore[no-untyped-def]
    return await repository.create_source(
        session,
        vault,
        workspace_id=ws,
        created_by=user,
        name="demo",
        host="db.internal",
        port=5432,
        database="sales",
        username="ro",
        password=PASSWORD,
        ssl_mode="prefer",
    )


async def test_password_is_stored_encrypted_and_recoverable(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    vault = _vault()
    async with scoped(app_engine, ws) as session:
        source = await _create(session, vault, ws, user)
        await session.commit()
        source_id = source.id
    async with owner_engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT password_encrypted FROM data_sources WHERE id = :i"), {"i": source_id}
            )
        ).scalar_one()
    assert PASSWORD not in stored
    async with scoped(app_engine, ws) as session:
        source = await repository.get_source(session, ws, source_id)
        assert source is not None
        params = repository.params_for(source, vault)
    assert params == ConnectionParams("db.internal", 5432, "sales", "ro", PASSWORD, "prefer")


async def test_read_schema_has_no_password_field() -> None:
    assert "password" not in DataSourceRead.model_fields
    assert not any("password" in name for name in DataSourceRead.model_fields)


async def test_create_schema_is_strict() -> None:
    base = {
        "name": "n",
        "host": "h",
        "port": 5432,
        "database": "d",
        "username": "u",
        "password": PASSWORD,
    }
    created = DataSourceCreate(**base)
    assert PASSWORD not in repr(created) and PASSWORD not in str(created.model_dump())
    for bad in ({"port": 0}, {"port": 70000}, {"host": ""}, {"extra": 1}, {"ssl_mode": "weird"}):
        with pytest.raises(ValidationError):
            DataSourceCreate(**{**base, **bad})


async def test_sources_are_isolated_between_workspaces(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user = await insert_user(owner_engine, "a@example.com")
    vault = _vault()
    async with scoped(app_engine, ws_a) as session:
        source = await _create(session, vault, ws_a, user)
        await session.commit()
        source_id = source.id
    async with scoped(app_engine, ws_b) as session:
        assert await repository.get_source(session, ws_b, source_id) is None
        assert await repository.list_sources(session, ws_b) == []
        assert await repository.delete_source(session, ws_b, source_id) is False
    async with scoped(app_engine, ws_a) as session:
        assert [s.id for s in await repository.list_sources(session, ws_a)] == [source_id]
        assert await repository.delete_source(session, ws_a, source_id) is True
        await session.commit()
    async with scoped(app_engine, ws_a) as session:
        assert await repository.list_sources(session, ws_a) == []


async def test_status_update_and_latest_snapshot(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    first = [TableInfo("t", [ColumnInfo("a", "integer", False, [])], ["a"], [], 1)]
    second = [
        TableInfo(
            "u",
            [ColumnInfo("b", "text", True, ["x"])],
            [],
            [ForeignKey(["b"], "t", ["a"])],
            2,
        )
    ]
    async with scoped(app_engine, ws) as session:
        source = await _create(session, _vault(), ws, user)
        assert source.status == "untested"
        await repository.set_source_status(session, source, ok=False, error="boom")
        assert (source.status, source.last_error) == ("failed", "boom")
        await repository.set_source_status(session, source, ok=True, error=None)
        assert (source.status, source.last_error) == ("ok", None)
        assert await repository.latest_snapshot(session, ws, source.id) is None
        await repository.save_snapshot(session, ws, source.id, first)
        await repository.save_snapshot(session, ws, source.id, second)
        await session.commit()
        source_id = source.id
    async with scoped(app_engine, ws) as session:  # RLS context ends with the transaction
        assert await repository.latest_snapshot(session, ws, source_id) == second


async def test_snapshot_of_a_real_discovery_survives_the_database(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, target_database: TargetDb
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    ro = target_database.readonly
    assert isinstance(ro, ConnectionParams)
    async with open_engine(ro) as target:
        tables = await discover_schema(target)
    async with scoped(app_engine, ws) as session:
        source = await _create(session, _vault(), ws, user)
        await repository.save_snapshot(session, ws, source.id, tables)
        await session.commit()
        source_id = source.id
    async with scoped(app_engine, ws) as session:
        assert await repository.latest_snapshot(session, ws, source_id) == tables
