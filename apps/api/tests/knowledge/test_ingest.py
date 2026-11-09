import pytest

from nawa.core.config import Settings
from nawa.intelligence.gateway import LLMGateway, LLMUnavailableError
from nawa.knowledge.extract import UnsupportedDocumentError
from nawa.knowledge.ingest import (
    EMBED_BATCH,
    MAX_ERROR_CHARS,
    EmbeddingError,
    EmptyDocumentError,
    build_chunks,
    describe_error,
    embed_in_batches,
)
from tests.fakes import FakeLLMClient
from tests.knowledge.pdfs import make_pdf


def _gateway(client: FakeLLMClient) -> LLMGateway:
    settings = Settings(
        _env_file=None,
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        llm_fallback_model="",
    )
    return LLMGateway(client, settings, model="ollama/qwen2.5:7b")


async def test_embed_in_batches_splits_and_keeps_order() -> None:
    fake = FakeLLMClient()
    texts = [f"text {i}" for i in range(EMBED_BATCH * 2 + 3)]
    vectors = await embed_in_batches(_gateway(fake), texts)
    assert len(vectors) == len(texts)
    assert [len(c["inputs"]) for c in fake.calls] == [EMBED_BATCH, EMBED_BATCH, 3]
    assert vectors[0] != vectors[1]


async def test_wrong_dimension_fails_loudly() -> None:
    class ShortEmbed(FakeLLMClient):
        async def embed(self, *, model, inputs, api_base):  # type: ignore[no-untyped-def]
            return [[0.1, 0.2] for _ in inputs]

    with pytest.raises(EmbeddingError, match="2 dimensions"):
        await embed_in_batches(_gateway(ShortEmbed()), ["a"])


async def test_wrong_count_fails_loudly() -> None:
    class FewEmbed(FakeLLMClient):
        async def embed(self, *, model, inputs, api_base):  # type: ignore[no-untyped-def]
            return []

    with pytest.raises(EmbeddingError, match="Expected 1"):
        await embed_in_batches(_gateway(FewEmbed()), ["a"])


def test_build_chunks_from_markdown() -> None:
    body = " ".join(f"Sentence {i} about the procedure." for i in range(120))
    data = f"# Refund\n\n{body}\n\n# Safety\n\n{body}\n".encode()
    built = build_chunks(data, "a.md", max_pages=200, chunker_name="heading")
    assert [c.ordinal for c in built.chunks] == list(range(len(built.chunks)))
    assert {c.heading for c in built.chunks} >= {"Refund", "Safety"}
    assert built.page_count is None


def test_build_chunks_reports_pdf_page_count() -> None:
    pdf = make_pdf([["Page one text here."], ["Page two text here."]])
    built = build_chunks(pdf, "a.pdf", max_pages=200, chunker_name="heading")
    assert built.page_count == 2


def test_corrupt_pdf_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError, match="could not be read"):
        build_chunks(b"%PDF-1.4\nnot really", "a.pdf", max_pages=200, chunker_name="heading")


def test_whitespace_only_document_is_empty() -> None:
    with pytest.raises((EmptyDocumentError, UnsupportedDocumentError)):
        build_chunks(b"   \n\n  ", "a.txt", max_pages=200, chunker_name="heading")


def test_describe_error_keeps_known_messages_and_hides_unknown() -> None:
    assert "boom" in describe_error(LLMUnavailableError("boom"))
    assert describe_error(RuntimeError("secret /path/x")) == "Unexpected error (RuntimeError)"
    assert "missing" in describe_error(FileNotFoundError("/data/x"))
    assert len(describe_error(EmbeddingError("x" * 1000))) <= MAX_ERROR_CHARS
