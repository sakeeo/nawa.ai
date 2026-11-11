import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from nawa.core.db import apply_rls
from tests.integration.helpers import insert_membership, insert_user, insert_workspace

TABLES = ["data_sources", "schema_snapshots", "semantic_models", "query_logs", "approved_queries"]


@dataclass
class Seed:
    ws_a: uuid.UUID
    ws_b: uuid.UUID
    user_a: uuid.UUID
    source_a: uuid.UUID


async def _populate(conn: AsyncConnection, ws: uuid.UUID, user: uuid.UUID) -> uuid.UUID:
    source = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO data_sources (id, workspace_id, name, kind, host, port, database,"
            " username, password_encrypted, created_by)"
            " VALUES (:id, :ws, 'demo', 'postgres', 'db', 5432, 'noesantara', 'ro', 'cipher', :u)"
        ),
        {"id": source, "ws": ws, "u": user},
    )
    await conn.execute(
        text(
            "INSERT INTO schema_snapshots (id, workspace_id, data_source_id, snapshot)"
            " VALUES (:id, :ws, :s, '{}'::jsonb)"
        ),
        {"id": uuid.uuid4(), "ws": ws, "s": source},
    )
    await conn.execute(
        text(
            "INSERT INTO semantic_models (id, workspace_id, data_source_id, version, yaml,"
            " is_active, created_by) VALUES (:id, :ws, :s, 1, 'tables: []', true, :u)"
        ),
        {"id": uuid.uuid4(), "ws": ws, "s": source, "u": user},
    )
    await conn.execute(
        text(
            "INSERT INTO query_logs (id, workspace_id, data_source_id, user_id, question, sql,"
            " status, attempts, duration_ms)"
            " VALUES (:id, :ws, :s, :u, 'q', 'SELECT 1', 'ok', 1, 5)"
        ),
        {"id": uuid.uuid4(), "ws": ws, "s": source, "u": user},
    )
    await conn.execute(
        text(
            "INSERT INTO approved_queries (id, workspace_id, data_source_id, question, sql,"
            " embedding, approved_by) VALUES (:id, :ws, :s, 'q', 'SELECT 1', :emb, :u)"
        ),
        {
            "id": uuid.uuid4(),
            "ws": ws,
            "s": source,
            "u": user,
            "emb": "[" + ",".join(["0.1"] * 1024) + "]",
        },
    )
    return source


@pytest_asyncio.fixture
async def seed(owner_engine: AsyncEngine) -> Seed:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user_a = await insert_user(owner_engine, "a@example.com")
    user_b = await insert_user(owner_engine, "b@example.com")
    await insert_membership(owner_engine, ws_a, user_a, "manager")
    await insert_membership(owner_engine, ws_b, user_b, "manager")
    async with owner_engine.begin() as conn:
        source_a = await _populate(conn, ws_a, user_a)
        await _populate(conn, ws_b, user_b)
    return Seed(ws_a, ws_b, user_a, source_a)


@asynccontextmanager
async def scoped(
    engine: AsyncEngine,
    *,
    workspace_id: uuid.UUID | None = None,
    is_admin: bool = False,
) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine) as session:
        await apply_rls(session, workspace_id=workspace_id, is_admin=is_admin)
        yield session


async def count(session: AsyncSession, table: str) -> int:
    return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_without_context_no_rows_are_visible(app_engine: AsyncEngine, seed: Seed) -> None:
    async with scoped(app_engine) as session:
        for table in TABLES:
            assert await count(session, table) == 0, table


async def test_workspace_context_sees_only_its_own_rows(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with scoped(app_engine, workspace_id=seed.ws_a) as session:
        for table in TABLES:
            rows = (await session.execute(text(f"SELECT workspace_id FROM {table}"))).scalars()
            assert set(rows) == {seed.ws_a}, table


async def test_admin_context_sees_every_workspace(app_engine: AsyncEngine, seed: Seed) -> None:
    async with scoped(app_engine, is_admin=True) as session:
        for table in TABLES:
            assert await count(session, table) == 2, table


async def test_cannot_insert_into_another_workspace(app_engine: AsyncEngine, seed: Seed) -> None:
    with pytest.raises(DBAPIError):
        async with scoped(app_engine, workspace_id=seed.ws_a) as session:
            await session.execute(
                text(
                    "INSERT INTO data_sources (id, workspace_id, name, kind, host, port, database,"
                    " username, password_encrypted)"
                    " VALUES (:id, :ws, 'x', 'postgres', 'h', 5432, 'd', 'u', 'c')"
                ),
                {"id": uuid.uuid4(), "ws": seed.ws_b},
            )


async def test_cannot_insert_query_log_into_another_workspace(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    with pytest.raises(DBAPIError):
        async with scoped(app_engine, workspace_id=seed.ws_a) as session:
            await session.execute(
                text(
                    "INSERT INTO query_logs (id, workspace_id, user_id, question, status,"
                    " attempts, duration_ms) VALUES (:id, :ws, :u, 'q', 'ok', 1, 1)"
                ),
                {"id": uuid.uuid4(), "ws": seed.ws_b, "u": seed.user_a},
            )


async def test_force_row_level_security_is_on(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                " WHERE relname = ANY(:names)"
            ),
            {"names": TABLES},
        )
        found = {r[0]: (r[1], r[2]) for r in rows}
    assert set(found) == set(TABLES)
    assert all(flags == (True, True) for flags in found.values())


async def test_app_role_cannot_alter_or_drop_data_tables(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    for statement in ("DROP TABLE data_sources", "ALTER TABLE query_logs ADD COLUMN x int"):
        with pytest.raises(DBAPIError):
            async with scoped(app_engine, workspace_id=seed.ws_a) as session:
                await session.execute(text(statement))


async def test_at_most_one_active_semantic_model_per_source(
    owner_engine: AsyncEngine, seed: Seed
) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO semantic_models (id, workspace_id, data_source_id, version,"
                    " yaml, is_active) VALUES (:id, :ws, :s, 2, 'tables: []', true)"
                ),
                {"id": uuid.uuid4(), "ws": seed.ws_a, "s": seed.source_a},
            )


async def test_inactive_versions_may_coexist(owner_engine: AsyncEngine, seed: Seed) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO semantic_models (id, workspace_id, data_source_id, version,"
                " yaml, is_active) VALUES (:id, :ws, :s, 2, 'tables: []', false)"
            ),
            {"id": uuid.uuid4(), "ws": seed.ws_a, "s": seed.source_a},
        )


async def test_semantic_model_version_is_unique_per_source(
    owner_engine: AsyncEngine, seed: Seed
) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO semantic_models (id, workspace_id, data_source_id, version,"
                    " yaml, is_active) VALUES (:id, :ws, :s, 1, 'tables: []', false)"
                ),
                {"id": uuid.uuid4(), "ws": seed.ws_a, "s": seed.source_a},
            )


async def test_data_source_name_is_unique_per_workspace(
    owner_engine: AsyncEngine, seed: Seed
) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO data_sources (id, workspace_id, name, kind, host, port, database,"
                    " username, password_encrypted)"
                    " VALUES (:id, :ws, 'demo', 'postgres', 'h', 5432, 'd', 'u', 'c')"
                ),
                {"id": uuid.uuid4(), "ws": seed.ws_a},
            )


async def test_check_constraints_reject_bad_values(owner_engine: AsyncEngine, seed: Seed) -> None:
    for statement in (
        "UPDATE query_logs SET status = 'weird'",
        "UPDATE query_logs SET feedback = 5",
        "UPDATE data_sources SET status = 'weird'",
        "UPDATE data_sources SET kind = 'mysql'",
    ):
        with pytest.raises(IntegrityError):
            async with owner_engine.begin() as conn:
                await conn.execute(text(statement))


async def test_data_source_defaults(owner_engine: AsyncEngine, seed: Seed) -> None:
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, ssl_mode FROM data_sources WHERE id = :s"),
                {"s": seed.source_a},
            )
        ).one()
    assert tuple(row) == ("untested", "prefer")


async def test_one_approved_query_per_question_and_source(
    owner_engine: AsyncEngine, seed: Seed
) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO approved_queries (id, workspace_id, data_source_id, question, sql,"
                    " embedding) VALUES (:id, :ws, :s, 'q', 'SELECT 2', :emb)"
                ),
                {
                    "id": uuid.uuid4(),
                    "ws": seed.ws_a,
                    "s": seed.source_a,
                    "emb": "[" + ",".join(["0.2"] * 1024) + "]",
                },
            )


async def test_approved_queries_have_a_vector_index(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        names = {
            r[0]
            for r in await conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'approved_queries'")
            )
        }
    assert "approved_queries_embedding_hnsw" in names


async def test_deleting_a_source_keeps_logs_but_drops_snapshots_and_models(
    owner_engine: AsyncEngine, seed: Seed
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM data_sources WHERE id = :s"), {"s": seed.source_a})
        assert (await conn.execute(text("SELECT count(*) FROM schema_snapshots"))).scalar_one() == 1
        assert (await conn.execute(text("SELECT count(*) FROM semantic_models"))).scalar_one() == 1
        logs = (
            (
                await conn.execute(
                    text("SELECT data_source_id FROM query_logs WHERE workspace_id = :ws"),
                    {"ws": seed.ws_a},
                )
            )
            .scalars()
            .all()
        )
    assert logs == [None]


async def test_deleting_a_workspace_cascades(owner_engine: AsyncEngine, seed: Seed) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM workspaces WHERE id = :ws"), {"ws": seed.ws_a})
        for table in TABLES:
            rows = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert rows == 1, table
