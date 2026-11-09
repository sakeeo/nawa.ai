import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nawa.core.config import Settings
from nawa.core.db import apply_rls
from nawa.intelligence.gateway import LLMGateway
from nawa.knowledge.ingest import ingest_document
from nawa.knowledge.retrieval import retrieve
from nawa.knowledge.storage import FileStorage
from tests.fakes import FakeLLMClient
from tests.integration.helpers import insert_user, insert_workspace

# Concept groups: texts and questions that share a group point the same way in vector space,
# so a question can match "by meaning" without sharing a single word with the chunk.
GROUPS = [
    {"chiller", "pendingin", "kulkas"},
    {"refund", "pengembalian", "uang"},
    {"sapi", "daging", "beef"},
    {"cuti", "libur"},
]


class ConceptEmbedder(FakeLLMClient):
    async def embed(self, *, model, inputs, api_base):  # type: ignore[no-untyped-def]
        out = []
        for value in inputs:
            words = set(value.lower().replace(".", " ").split())
            vector = [0.001] * 1024
            for i, group in enumerate(GROUPS):
                vector[i] += len(words & group)
            out.append(vector)
        return out


def _settings(**overrides: int) -> Settings:
    return Settings(
        _env_file=None,
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        llm_fallback_model="",
        **overrides,
    )


def _gateway() -> LLMGateway:
    return LLMGateway(ConceptEmbedder(), _settings(), model="ollama/qwen2.5:7b")


DOCS = {
    "chiller.md": "# Chiller\n\nSimpan bahan di chiller. Kode SKU-ZX9 untuk audit.",
    "refund.md": "# Refund\n\nProsedur refund penuh untuk pelanggan yang kecewa.",
    "sapi.md": "# Sapi\n\nDaging sapi diterima pagi hari dari pemasok.",
    "cuti.md": "# Cuti\n\nCuti tahunan diajukan seminggu sebelumnya.",
}


@pytest.fixture
async def corpus(
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> dict[str, uuid.UUID]:
    """Returns {"ws_a": ..., "ws_b": ..., "chiller.md": document id, ...} with chunks ingested."""
    storage = FileStorage(tmp_path)
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user = await insert_user(owner_engine, "u@example.com")
    ids: dict[str, uuid.UUID] = {"ws_a": ws_a, "ws_b": ws_b}
    kb = uuid.uuid4()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO knowledge_bases (id, workspace_id, name) VALUES (:id, :ws, 'D')"),
            {"id": kb, "ws": ws_a},
        )
        for name, body in DOCS.items():
            doc = uuid.uuid4()
            ids[name] = doc
            data = body.encode()
            await conn.execute(
                text(
                    "INSERT INTO documents (id, workspace_id, knowledge_base_id, filename, mime,"
                    " size_bytes, sha256, status, created_by)"
                    " VALUES (:id, :ws, :kb, :fn, 'text/markdown', :n, :sha, 'queued', :u)"
                ),
                {
                    "id": doc,
                    "ws": ws_a,
                    "kb": kb,
                    "fn": name,
                    "n": len(data),
                    "sha": str(doc),
                    "u": user,
                },
            )
            storage.save(ws_a, doc, data)
    for name in DOCS:
        await ingest_document(
            sessionmaker, storage, _gateway(), workspace_id=ws_a, document_id=ids[name]
        )
    return ids


async def _retrieve(
    maker: async_sessionmaker[AsyncSession],
    ws: uuid.UUID,
    question: str,
    strategy: str = "hybrid",
    settings: Settings | None = None,
):  # type: ignore[no-untyped-def]
    async with maker() as session:
        await apply_rls(session, workspace_id=ws)
        return await retrieve(
            session,
            _gateway(),
            question,
            settings=settings or _settings(),
            strategy=strategy,  # type: ignore[arg-type]
        )


async def test_vector_finds_the_chunk_by_meaning(
    corpus: dict[str, uuid.UUID], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await _retrieve(sessionmaker, corpus["ws_a"], "Bagaimana pengembalian uang?", "vector")
    assert result[0].filename == "refund.md"
    assert result[0].vector_rank == 1 and result[0].keyword_rank is None


async def test_keyword_finds_an_exact_rare_term(
    corpus: dict[str, uuid.UUID], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await _retrieve(sessionmaker, corpus["ws_a"], "audit SKU-ZX9", "keyword")
    assert [c.filename for c in result] == ["chiller.md"]
    assert result[0].keyword_rank == 1 and result[0].vector_rank is None


async def test_hybrid_returns_both_kinds_of_hit(
    corpus: dict[str, uuid.UUID], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await _retrieve(sessionmaker, corpus["ws_a"], "pengembalian uang SKU-ZX9")
    names = [c.filename for c in result]
    assert "refund.md" in names and "chiller.md" in names
    assert all(isinstance(c.similarity, float) for c in result)
    keyword_only = next(c for c in result if c.filename == "chiller.md")
    assert keyword_only.keyword_rank == 1
    scores = [c.rrf_score for c in result]
    assert scores == sorted(scores, reverse=True)


async def test_candidates_carry_citation_fields(
    corpus: dict[str, uuid.UUID], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    top = (await _retrieve(sessionmaker, corpus["ws_a"], "cuti libur"))[0]
    assert top.filename == "cuti.md" and top.document_id == corpus["cuti.md"]
    assert top.heading == "Cuti" and "tahunan" in top.text and top.similarity > 0.5


async def test_non_ready_documents_never_appear(
    corpus: dict[str, uuid.UUID],
    owner_engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE documents SET status = 'processing' WHERE id = :d"),
            {"d": corpus["refund.md"]},
        )
    for strategy in ("vector", "keyword", "hybrid"):
        result = await _retrieve(sessionmaker, corpus["ws_a"], "refund pengembalian uang", strategy)
        assert "refund.md" not in [c.filename for c in result]


async def test_other_workspace_sees_nothing(
    corpus: dict[str, uuid.UUID], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    for strategy in ("vector", "keyword", "hybrid"):
        assert (
            await _retrieve(sessionmaker, corpus["ws_b"], "refund chiller SKU-ZX9", strategy) == []
        )


async def test_limits_are_respected(
    corpus: dict[str, uuid.UUID], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await _retrieve(
        sessionmaker, corpus["ws_a"], "refund chiller cuti sapi", settings=_settings(rag_final_k=2)
    )
    assert len(result) == 2
    result = await _retrieve(
        sessionmaker,
        corpus["ws_a"],
        "refund chiller cuti sapi",
        "vector",
        _settings(rag_vector_k=1),
    )
    assert len(result) == 1


async def test_operator_characters_in_a_question_are_harmless(
    corpus: dict[str, uuid.UUID], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    result = await _retrieve(sessionmaker, corpus["ws_a"], "refund & ! ( | ) :* 'x'", "keyword")
    assert [c.filename for c in result] == ["refund.md"]
