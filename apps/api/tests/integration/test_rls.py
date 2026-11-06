import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nawa.core.db import apply_rls
from tests.integration.helpers import (
    insert_membership,
    insert_user,
    insert_workspace,
)

TENANT_TABLES = ["memberships", "invites", "audit_logs"]


@dataclass
class Seed:
    ws_a: uuid.UUID
    ws_b: uuid.UUID
    user_a: uuid.UUID
    user_b: uuid.UUID


@pytest_asyncio.fixture
async def seed(owner_engine: AsyncEngine) -> Seed:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user_a = await insert_user(owner_engine, "a@example.com")
    user_b = await insert_user(owner_engine, "b@example.com")
    await insert_membership(owner_engine, ws_a, user_a, "member")
    await insert_membership(owner_engine, ws_b, user_b, "member")
    async with owner_engine.begin() as conn:
        for workspace_id, user_id in ((ws_a, user_a), (ws_b, user_b)):
            await conn.execute(
                text(
                    "INSERT INTO invites (id, email, token_hash, workspace_id, role, expires_at)"
                    " VALUES (:id, :email, :hash, :ws, 'member', now() + interval '1 day')"
                ),
                {
                    "id": uuid.uuid4(),
                    "email": f"invitee-{workspace_id}@example.com",
                    "hash": uuid.uuid4().hex,
                    "ws": workspace_id,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO audit_logs (id, workspace_id, actor_id, action)"
                    " VALUES (:id, :ws, :actor, 'seed')"
                ),
                {"id": uuid.uuid4(), "ws": workspace_id, "actor": user_id},
            )
        await conn.execute(
            text("INSERT INTO audit_logs (id, action) VALUES (:id, 'global')"),
            {"id": uuid.uuid4()},
        )
    return Seed(ws_a, ws_b, user_a, user_b)


@asynccontextmanager
async def scoped(
    engine: AsyncEngine,
    *,
    workspace_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    is_admin: bool = False,
) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine) as session:
        await apply_rls(session, workspace_id=workspace_id, user_id=user_id, is_admin=is_admin)
        yield session


async def column_values(session: AsyncSession, table: str, column: str) -> list[object]:
    result = await session.execute(text(f"SELECT {column} FROM {table}"))
    return list(result.scalars().all())


async def test_without_context_no_tenant_rows_are_visible(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with scoped(app_engine) as session:
        for table in (*TENANT_TABLES, "workspaces"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, table


async def test_workspace_context_sees_only_its_own_rows(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with scoped(app_engine, workspace_id=seed.ws_a) as session:
        for table in TENANT_TABLES:
            values = await column_values(session, table, "workspace_id")
            assert values, table
            assert set(values) == {seed.ws_a}, table
        assert set(await column_values(session, "workspaces", "id")) == {seed.ws_a}


async def test_global_audit_rows_are_hidden_from_a_workspace_context(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with scoped(app_engine, workspace_id=seed.ws_a) as session:
        assert None not in await column_values(session, "audit_logs", "workspace_id")


async def test_admin_context_sees_every_workspace(app_engine: AsyncEngine, seed: Seed) -> None:
    async with scoped(app_engine, is_admin=True) as session:
        for table in TENANT_TABLES:
            values = await column_values(session, table, "workspace_id")
            assert {seed.ws_a, seed.ws_b} <= set(values), table
        assert None in await column_values(session, "audit_logs", "workspace_id")
        assert set(await column_values(session, "workspaces", "id")) == {seed.ws_a, seed.ws_b}


async def test_user_context_sees_own_memberships_and_workspaces_only(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with scoped(app_engine, user_id=seed.user_a) as session:
        assert await column_values(session, "memberships", "user_id") == [seed.user_a]
        assert set(await column_values(session, "workspaces", "id")) == {seed.ws_a}


async def test_cannot_insert_into_another_workspace(app_engine: AsyncEngine, seed: Seed) -> None:
    with pytest.raises(DBAPIError):
        async with scoped(app_engine, workspace_id=seed.ws_a) as session:
            await session.execute(
                text(
                    "INSERT INTO invites (id, email, token_hash, workspace_id, role, expires_at)"
                    " VALUES (:id, 'x@example.com', :hash, :ws, 'member', now())"
                ),
                {"id": uuid.uuid4(), "hash": uuid.uuid4().hex, "ws": seed.ws_b},
            )


async def test_cannot_update_or_delete_another_workspace_rows(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with scoped(app_engine, workspace_id=seed.ws_a) as session:
        updated = await session.execute(
            text("UPDATE memberships SET role = 'viewer' WHERE workspace_id = :ws"),
            {"ws": seed.ws_b},
        )
        deleted = await session.execute(
            text("DELETE FROM memberships WHERE workspace_id = :ws"), {"ws": seed.ws_b}
        )
        assert updated.rowcount == 0  # type: ignore[attr-defined]
        assert deleted.rowcount == 0  # type: ignore[attr-defined]


async def test_non_admin_cannot_write_workspaces(app_engine: AsyncEngine, seed: Seed) -> None:
    with pytest.raises(DBAPIError):
        async with scoped(app_engine, workspace_id=seed.ws_a, user_id=seed.user_a) as session:
            await session.execute(
                text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'N', 'n')"),
                {"id": uuid.uuid4()},
            )


async def test_context_does_not_leak_across_transactions(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with AsyncSession(app_engine) as session:
        await apply_rls(session, workspace_id=seed.ws_a)
        before = (await session.execute(text("SELECT count(*) FROM invites"))).scalar_one()
        await session.commit()
        after = (await session.execute(text("SELECT count(*) FROM invites"))).scalar_one()
    assert before == 1
    assert after == 0
