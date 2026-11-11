import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nawa.core.config import Settings
from nawa.core.crypto import CredentialVault
from nawa.core.db import apply_rls
from nawa.data import repository
from nawa.data.fewshot import approve_query, similar_examples, unapprove_query
from nawa.intelligence.gateway import LLMGateway
from tests.fakes import ConceptEmbedder, FakeLLMClient
from tests.integration.helpers import insert_user, insert_workspace


@asynccontextmanager
async def scoped(engine: AsyncEngine, ws: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await apply_rls(session, workspace_id=ws)
        yield session


def gateway(client: FakeLLMClient) -> LLMGateway:
    settings = Settings(_env_file=None, database_url="x", redis_url="x", jwt_secret="s" * 32)  # type: ignore[call-arg]
    return LLMGateway(client, settings, "deepseek/deepseek-chat")


async def make_source(
    session: AsyncSession, ws: uuid.UUID, user: uuid.UUID, name: str = "demo"
) -> uuid.UUID:
    source = await repository.create_source(
        session,
        CredentialVault(Fernet.generate_key().decode()),
        workspace_id=ws,
        created_by=user,
        name=name,
        host="h",
        port=5432,
        database="d",
        username="u",
        password="p",
        ssl_mode="prefer",
    )
    return source.id


async def log(
    session: AsyncSession,
    ws: uuid.UUID,
    user: uuid.UUID,
    source: uuid.UUID | None,
    question: str,
    *,
    status: str = "ok",
    sql: str | None = "SELECT 1 LIMIT 1000",
):  # type: ignore[no-untyped-def]
    query_id = await repository.log_query(
        session,
        workspace_id=ws,
        user_id=user,
        data_source_id=source,
        question=question,
        sql=sql,
        status=status,
        blocked_reason=None,
        attempts=1,
        row_count=1,
        duration_ms=1,
    )
    entry = await repository.get_query(session, ws, query_id)
    assert entry is not None
    return entry


async def test_an_approved_query_is_found_for_a_similar_question_only(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    gw = gateway(ConceptEmbedder())
    async with scoped(app_engine, ws) as session:
        source = await make_source(session, ws, user)
        entry = await log(
            session, ws, user, source, "berapa daging sapi terjual", sql="SELECT 7 LIMIT 1000"
        )
        assert await approve_query(session, gw, entry=entry, approved_by=user) is True
        await session.commit()
    async with scoped(app_engine, ws) as session:
        found = await similar_examples(
            session, gw, workspace_id=ws, source_id=source, question="total beef daging"
        )
        assert found == [("berapa daging sapi terjual", "SELECT 7 LIMIT 1000")]
        unrelated = await similar_examples(
            session, gw, workspace_id=ws, source_id=source, question="aturan cuti libur"
        )
        assert unrelated == []
        strict = await similar_examples(
            session,
            gw,
            workspace_id=ws,
            source_id=source,
            question="total beef daging",
            min_similarity=1.01,
        )
        assert strict == []


async def test_only_successful_queries_with_sql_and_a_source_can_be_approved(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    gw = gateway(ConceptEmbedder())
    async with scoped(app_engine, ws) as session:
        source = await make_source(session, ws, user)
        for status in ("blocked", "error", "clarification"):
            entry = await log(session, ws, user, source, f"q {status}", status=status)
            assert await approve_query(session, gw, entry=entry, approved_by=user) is False
        no_sql = await log(session, ws, user, source, "no sql", sql=None)
        assert await approve_query(session, gw, entry=no_sql, approved_by=user) is False
        orphan = await log(session, ws, user, None, "orphan")
        assert await approve_query(session, gw, entry=orphan, approved_by=user) is False
        await session.commit()
    async with owner_engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM approved_queries"))).scalar_one() == 0


async def test_approving_the_same_question_again_replaces_the_sql(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    gw = gateway(ConceptEmbedder())
    async with scoped(app_engine, ws) as session:
        source = await make_source(session, ws, user)
        first = await log(
            session, ws, user, source, "refund pengembalian", sql="SELECT 1 LIMIT 1000"
        )
        await approve_query(session, gw, entry=first, approved_by=user)
        second = await log(
            session, ws, user, source, "refund pengembalian", sql="SELECT 2 LIMIT 1000"
        )
        await approve_query(session, gw, entry=second, approved_by=user)
        await session.commit()
    async with owner_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT sql FROM approved_queries"))).scalars().all()
    assert rows == ["SELECT 2 LIMIT 1000"]


async def test_unapproving_removes_the_example(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    gw = gateway(ConceptEmbedder())
    async with scoped(app_engine, ws) as session:
        source = await make_source(session, ws, user)
        entry = await log(session, ws, user, source, "cuti libur")
        await approve_query(session, gw, entry=entry, approved_by=user)
        assert await unapprove_query(session, ws, source, "cuti libur") is True
        assert await unapprove_query(session, ws, source, "cuti libur") is False
        await session.commit()
    async with scoped(app_engine, ws) as session:
        assert (
            await similar_examples(
                session, gw, workspace_id=ws, source_id=source, question="cuti libur"
            )
            == []
        )


async def test_examples_never_cross_workspaces_or_data_sources(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user = await insert_user(owner_engine, "a@example.com")
    gw = gateway(ConceptEmbedder())
    async with scoped(app_engine, ws_a) as session:
        source_a = await make_source(session, ws_a, user)
        other_source = await make_source(session, ws_a, user, name="second")
        await approve_query(
            session,
            gw,
            entry=await log(session, ws_a, user, source_a, "refund uang"),
            approved_by=user,
        )
        await session.commit()
    async with scoped(app_engine, ws_b) as session:
        source_b = await make_source(session, ws_b, user)
        assert (
            await similar_examples(
                session, gw, workspace_id=ws_b, source_id=source_b, question="refund uang"
            )
            == []
        )
        assert (
            await similar_examples(
                session, gw, workspace_id=ws_a, source_id=source_a, question="refund uang"
            )
            == []
        )  # RLS
    async with scoped(app_engine, ws_a) as session:
        assert (
            await similar_examples(
                session, gw, workspace_id=ws_a, source_id=other_source, question="refund uang"
            )
            == []
        )
        assert (
            len(
                await similar_examples(
                    session, gw, workspace_id=ws_a, source_id=source_a, question="refund uang"
                )
            )
            == 1
        )


async def test_an_embedding_failure_means_no_examples_not_an_error(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    class Broken(FakeLLMClient):
        async def embed(self, *, model: str, inputs: list[str], api_base: str | None):  # type: ignore[no-untyped-def]
            raise RuntimeError("down")

    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    async with scoped(app_engine, ws) as session:
        source = await make_source(session, ws, user)
        entry = await log(session, ws, user, source, "refund uang")
        assert (
            await approve_query(session, gateway(Broken()), entry=entry, approved_by=user) is False
        )
        assert (
            await similar_examples(
                session, gateway(Broken()), workspace_id=ws, source_id=source, question="x"
            )
            == []
        )


async def test_deleting_the_source_deletes_its_examples(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    gw = gateway(ConceptEmbedder())
    async with scoped(app_engine, ws) as session:
        source = await make_source(session, ws, user)
        await approve_query(
            session, gw, entry=await log(session, ws, user, source, "refund uang"), approved_by=user
        )
        await session.commit()
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM data_sources WHERE id = :s"), {"s": source})
        assert (await conn.execute(text("SELECT count(*) FROM approved_queries"))).scalar_one() == 0
