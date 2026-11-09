import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nawa.core.config import Settings
from nawa.intelligence.gateway import LLMGateway, LLMUnavailableError
from nawa.knowledge.ingest import ingest_document
from nawa.knowledge.storage import FileStorage
from tests.fakes import FakeLLMClient
from tests.integration.helpers import insert_user, insert_workspace
from tests.knowledge.pdfs import make_pdf

_LONG = " ".join(f"Sentence {i} about the procedure." for i in range(120))
MD = f"# Refund\n\n{_LONG}\n\n# Safety\n\n{_LONG}\n".encode()


def _gateway(client: FakeLLMClient) -> LLMGateway:
    settings = Settings(
        _env_file=None,
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        llm_fallback_model="",
    )
    return LLMGateway(client, settings, model="ollama/qwen2.5:7b")


async def _seed(
    engine: AsyncEngine, storage: FileStorage, data: bytes, filename: str
) -> tuple[uuid.UUID, uuid.UUID]:
    ws = await insert_workspace(engine, f"ws-{uuid.uuid4().hex[:6]}")
    user = await insert_user(engine, f"u{uuid.uuid4().hex[:6]}@example.com")
    kb, doc = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO knowledge_bases (id, workspace_id, name) VALUES (:id, :ws, 'D')"),
            {"id": kb, "ws": ws},
        )
        await conn.execute(
            text(
                "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime,"
                " size_bytes, sha256, status, created_by)"
                " VALUES (:id, :ws, :kb, :fn, 'text/plain', :n, :sha, 'queued', :u)"
            ),
            {
                "id": doc,
                "ws": ws,
                "kb": kb,
                "fn": filename,
                "n": len(data),
                "sha": str(doc),
                "u": user,
            },
        )
    storage.save(ws, doc, data)
    return ws, doc


async def _state(engine: AsyncEngine, doc: uuid.UUID) -> tuple[str, str | None, int | None, int]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, error, page_count FROM documents WHERE id = :d"), {"d": doc}
            )
        ).one()
        count = (
            await conn.execute(
                text("SELECT count(*) FROM chunks WHERE document_id = :d"), {"d": doc}
            )
        ).scalar_one()
    return row[0], row[1], row[2], count


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    return FileStorage(tmp_path)


async def test_ingestion_stores_ordered_chunks_with_embeddings(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    ws, doc = await _seed(owner_engine, storage, MD, "policy.md")
    await ingest_document(
        sessionmaker, storage, _gateway(FakeLLMClient()), workspace_id=ws, document_id=doc
    )
    status, error, _, count = await _state(owner_engine, doc)
    assert (status, error) == ("ready", None)
    assert count >= 2
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT ordinal, vector_dims(embedding) FROM chunks"
                    " WHERE document_id = :d ORDER BY ordinal"
                ),
                {"d": doc},
            )
        ).all()
    assert [r[0] for r in rows] == list(range(count))
    assert {r[1] for r in rows} == {1024}


async def test_pdf_page_count_is_recorded(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    pdf = make_pdf([["First page."], ["Second page."]])
    ws, doc = await _seed(owner_engine, storage, pdf, "a.pdf")
    await ingest_document(
        sessionmaker, storage, _gateway(FakeLLMClient()), workspace_id=ws, document_id=doc
    )
    status, _, pages, _ = await _state(owner_engine, doc)
    assert (status, pages) == ("ready", 2)


async def test_corrupt_pdf_fails_with_a_clear_error(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    ws, doc = await _seed(owner_engine, storage, b"%PDF-1.4\ngarbage", "bad.pdf")
    await ingest_document(
        sessionmaker, storage, _gateway(FakeLLMClient()), workspace_id=ws, document_id=doc
    )
    status, error, _, count = await _state(owner_engine, doc)
    assert status == "failed" and count == 0
    assert error and "could not be read" in error


async def test_rerunning_ingestion_leaves_one_chunk_set(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    ws, doc = await _seed(owner_engine, storage, MD, "policy.md")
    gateway = _gateway(FakeLLMClient())
    await ingest_document(sessionmaker, storage, gateway, workspace_id=ws, document_id=doc)
    first = (await _state(owner_engine, doc))[3]
    await ingest_document(sessionmaker, storage, gateway, workspace_id=ws, document_id=doc)
    status, _, _, second = await _state(owner_engine, doc)
    assert status == "ready" and second == first


async def test_embedding_failure_keeps_old_chunks_out_of_half_state(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    class Down(FakeLLMClient):
        async def embed(self, *, model, inputs, api_base):  # type: ignore[no-untyped-def]
            raise LLMUnavailableError("embedding model is down")

    ws, doc = await _seed(owner_engine, storage, MD, "policy.md")
    await ingest_document(sessionmaker, storage, _gateway(Down()), workspace_id=ws, document_id=doc)
    status, error, _, count = await _state(owner_engine, doc)
    assert status == "failed" and count == 0
    assert error and "down" in error


async def test_wrong_dimension_marks_failed(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    class Short(FakeLLMClient):
        async def embed(self, *, model, inputs, api_base):  # type: ignore[no-untyped-def]
            return [[0.1] * 8 for _ in inputs]

    ws, doc = await _seed(owner_engine, storage, MD, "policy.md")
    await ingest_document(
        sessionmaker, storage, _gateway(Short()), workspace_id=ws, document_id=doc
    )
    status, error, _, count = await _state(owner_engine, doc)
    assert status == "failed" and count == 0
    assert error and "dimensions" in error


async def test_missing_file_marks_failed(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    ws, doc = await _seed(owner_engine, storage, MD, "policy.md")
    storage.delete(ws, doc)
    await ingest_document(
        sessionmaker, storage, _gateway(FakeLLMClient()), workspace_id=ws, document_id=doc
    )
    status, error, _, _ = await _state(owner_engine, doc)
    assert status == "failed" and error and "missing" in error


async def test_unknown_document_is_skipped(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
) -> None:
    ws = await insert_workspace(owner_engine, "empty")
    await ingest_document(
        sessionmaker, storage, _gateway(FakeLLMClient()), workspace_id=ws, document_id=uuid.uuid4()
    )
