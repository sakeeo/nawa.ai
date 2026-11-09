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

TENANT_TABLES = [
    "knowledge_bases",
    "documents",
    "chunks",
    "conversations",
    "messages",
    "citations",
    "feedback",
    "eval_runs",
]
ALL_TABLES = [*TENANT_TABLES, "eval_results"]


@dataclass
class Seed:
    ws_a: uuid.UUID
    ws_b: uuid.UUID
    user_a: uuid.UUID
    user_b: uuid.UUID
    kb_a: uuid.UUID
    doc_a: uuid.UUID
    msg_a: uuid.UUID


async def _populate(conn: AsyncConnection, ws: uuid.UUID, user: uuid.UUID) -> tuple[uuid.UUID, ...]:
    kb, doc, chunk, conv, msg, run = (uuid.uuid4() for _ in range(6))
    run_sql = conn.execute
    await run_sql(
        text("INSERT INTO knowledge_bases (id, workspace_id, name) VALUES (:id, :ws, 'Default')"),
        {"id": kb, "ws": ws},
    )
    await run_sql(
        text(
            "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime,"
            " size_bytes, sha256, status, created_by)"
            " VALUES (:id, :ws, :kb, 'a.txt', 'text/plain', 3, :sha, 'ready', :u)"
        ),
        {"id": doc, "ws": ws, "kb": kb, "sha": f"sha-{doc}", "u": user},
    )
    await run_sql(
        text(
            "INSERT INTO chunks (id, workspace_id, document_id, ordinal, text, token_count,"
            " embedding) VALUES (:id, :ws, :doc, 0, 'refund policy text', 4, :emb)"
        ),
        {"id": chunk, "ws": ws, "doc": doc, "emb": "[" + ",".join(["0.1"] * 1024) + "]"},
    )
    await run_sql(
        text(
            "INSERT INTO conversations (id, workspace_id, user_id, title)"
            " VALUES (:id, :ws, :u, 't')"
        ),
        {"id": conv, "ws": ws, "u": user},
    )
    await run_sql(
        text(
            "INSERT INTO messages (id, workspace_id, conversation_id, role, content)"
            " VALUES (:id, :ws, :c, 'assistant', 'hi')"
        ),
        {"id": msg, "ws": ws, "c": conv},
    )
    await run_sql(
        text(
            "INSERT INTO citations (id, workspace_id, message_id, chunk_id, marker)"
            " VALUES (:id, :ws, :m, :ch, 1)"
        ),
        {"id": uuid.uuid4(), "ws": ws, "m": msg, "ch": chunk},
    )
    await run_sql(
        text(
            "INSERT INTO feedback (id, workspace_id, message_id, user_id, value)"
            " VALUES (:id, :ws, :m, :u, 1)"
        ),
        {"id": uuid.uuid4(), "ws": ws, "m": msg, "u": user},
    )
    await run_sql(
        text("INSERT INTO eval_runs (id, workspace_id, name) VALUES (:id, :ws, 'r')"),
        {"id": run, "ws": ws},
    )
    await run_sql(
        text(
            "INSERT INTO eval_results (id, eval_run_id, question_id, answer)"
            " VALUES (:id, :r, 'q1', 'a')"
        ),
        {"id": uuid.uuid4(), "r": run},
    )
    return kb, doc, msg


@pytest_asyncio.fixture
async def seed(owner_engine: AsyncEngine) -> Seed:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user_a = await insert_user(owner_engine, "a@example.com")
    user_b = await insert_user(owner_engine, "b@example.com")
    await insert_membership(owner_engine, ws_a, user_a, "member")
    await insert_membership(owner_engine, ws_b, user_b, "member")
    async with owner_engine.begin() as conn:
        kb_a, doc_a, msg_a = await _populate(conn, ws_a, user_a)
        await _populate(conn, ws_b, user_b)
    return Seed(ws_a, ws_b, user_a, user_b, kb_a, doc_a, msg_a)


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
        for table in ALL_TABLES:
            assert await count(session, table) == 0, table


async def test_workspace_context_sees_only_its_own_rows(
    app_engine: AsyncEngine, seed: Seed
) -> None:
    async with scoped(app_engine, workspace_id=seed.ws_a) as session:
        for table in TENANT_TABLES:
            rows = (await session.execute(text(f"SELECT workspace_id FROM {table}"))).scalars()
            assert set(rows) == {seed.ws_a}, table
        assert await count(session, "eval_results") == 1


async def test_admin_context_sees_every_workspace(app_engine: AsyncEngine, seed: Seed) -> None:
    async with scoped(app_engine, is_admin=True) as session:
        for table in ALL_TABLES:
            assert await count(session, table) == 2, table


async def test_cannot_insert_into_another_workspace(app_engine: AsyncEngine, seed: Seed) -> None:
    with pytest.raises(DBAPIError):
        async with scoped(app_engine, workspace_id=seed.ws_a) as session:
            await session.execute(
                text("INSERT INTO knowledge_bases (id, workspace_id, name) VALUES (:id, :ws, 'x')"),
                {"id": uuid.uuid4(), "ws": seed.ws_b},
            )


async def test_cannot_attach_eval_result_to_another_workspace_run(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, seed: Seed
) -> None:
    async with owner_engine.connect() as conn:
        run_b = (
            await conn.execute(
                text("SELECT id FROM eval_runs WHERE workspace_id = :ws"), {"ws": seed.ws_b}
            )
        ).scalar_one()
    with pytest.raises(DBAPIError):
        async with scoped(app_engine, workspace_id=seed.ws_a) as session:
            await session.execute(
                text(
                    "INSERT INTO eval_results (id, eval_run_id, question_id) VALUES (:id, :r, 'q')"
                ),
                {"id": uuid.uuid4(), "r": run_b},
            )


async def test_force_row_level_security_is_on(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                " WHERE relname = ANY(:names)"
            ),
            {"names": ALL_TABLES},
        )
        found = {r[0]: (r[1], r[2]) for r in rows}
    assert set(found) == set(ALL_TABLES)
    assert all(flags == (True, True) for flags in found.values())


async def test_extension_and_indexes_exist(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        ext = (
            await conn.execute(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'"))
        ).scalar_one()
        indexes = {
            r[0]
            for r in await conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")
            )
        }
    assert ext == 1
    assert {"chunks_embedding_hnsw", "chunks_tsv_gin"} <= indexes


async def test_duplicate_document_hash_in_one_knowledge_base_is_rejected(
    owner_engine: AsyncEngine, seed: Seed
) -> None:
    async with owner_engine.connect() as conn:
        sha = (
            await conn.execute(
                text("SELECT sha256 FROM documents WHERE id = :d"), {"d": seed.doc_a}
            )
        ).scalar_one()
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime,"
                    " size_bytes, sha256, status, created_by)"
                    " VALUES (:id, :ws, :kb, 'dup.txt', 'text/plain', 1, :sha, 'queued', :u)"
                ),
                {
                    "id": uuid.uuid4(),
                    "ws": seed.ws_a,
                    "kb": seed.kb_a,
                    "sha": sha,
                    "u": seed.user_a,
                },
            )


async def test_one_feedback_per_user_per_message(owner_engine: AsyncEngine, seed: Seed) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO feedback (id, workspace_id, message_id, user_id, value)"
                    " VALUES (:id, :ws, :m, :u, -1)"
                ),
                {"id": uuid.uuid4(), "ws": seed.ws_a, "m": seed.msg_a, "u": seed.user_a},
            )


async def test_check_constraints_reject_bad_values(owner_engine: AsyncEngine, seed: Seed) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE documents SET status = 'weird' WHERE id = :d"), {"d": seed.doc_a}
            )
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE feedback SET value = 5"))
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE messages SET role = 'system'"))


async def test_tsv_is_generated_from_text(owner_engine: AsyncEngine, seed: Seed) -> None:
    async with owner_engine.connect() as conn:
        hit = (
            await conn.execute(
                text("SELECT count(*) FROM chunks WHERE tsv @@ to_tsquery('simple', 'refund')")
            )
        ).scalar_one()
    assert hit == 2


async def test_deleting_a_workspace_cascades(owner_engine: AsyncEngine, seed: Seed) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM workspaces WHERE id = :ws"), {"ws": seed.ws_a})
        for table in ("documents", "chunks", "messages", "eval_results"):
            rows = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert rows == 1, table
