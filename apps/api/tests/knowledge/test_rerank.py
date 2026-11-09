import json
import logging
import uuid

import httpx
import pytest

from nawa.core.config import Settings
from nawa.knowledge.rerank import (
    NoopReranker,
    TEIReranker,
    get_reranker,
    rerank_with_fallback,
)
from nawa.knowledge.retrieval import Candidate

LOG = logging.getLogger("test.rerank")


def _cand(i: int) -> Candidate:
    return Candidate(
        chunk_id=uuid.UUID(int=i),
        document_id=uuid.UUID(int=100),
        filename="a.md",
        page=None,
        section_path="",
        heading=None,
        text=f"text {i}",
        similarity=0.5,
        vector_rank=i,
        keyword_rank=None,
        rrf_score=1 / (60 + i),
    )


CANDS = [_cand(1), _cand(2), _cand(3)]


def _client(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(**kw: object) -> Settings:
    # Explicit defaults: the repo .env may enable the reranker and leaks in via the environment.
    values: dict[str, object] = {"reranker_enabled": False, "reranker_url": ""}
    values.update(kw)
    return Settings(
        _env_file=None,
        database_url="x",
        redis_url="x",
        jwt_secret="s" * 32,
        **values,  # type: ignore[arg-type]
    )


async def test_scores_reorder_and_truncate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"index": 0, "score": 0.1},
                {"index": 2, "score": 0.9},
                {"index": 1, "score": 0.5},
            ],
        )

    async with _client(handler) as client:
        result = await TEIReranker("http://r", client).rerank("q", CANDS, top_n=2)
    assert [c.chunk_id.int for c in result] == [3, 2]
    assert [c.rerank_score for c in result] == [0.9, 0.5]
    assert result[0].rrf_score == CANDS[2].rrf_score  # other fields are kept


async def test_request_carries_query_and_texts_in_order() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[])

    async with _client(handler) as client:
        await TEIReranker("http://r/", client).rerank("pertanyaan", CANDS, top_n=5)
    assert seen["url"] == "http://r/rerank"
    assert seen["body"]["query"] == "pertanyaan"
    assert seen["body"]["texts"] == ["text 1", "text 2", "text 3"]


async def test_nothing_is_sent_without_candidates() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])

    async with _client(handler) as client:
        assert await TEIReranker("http://r", client).rerank("q", [], top_n=5) == []
        assert await rerank_with_fallback(
            TEIReranker("http://r", client), "q", [], top_n=5, log=LOG
        ) == ([], False)
    assert calls == 0


@pytest.mark.parametrize("failure", ["500", "timeout", "connect", "garbage", "bad-index"])
async def test_failures_fall_back_to_the_fused_order(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "500":
            return httpx.Response(500, text="boom")
        if failure == "timeout":
            raise httpx.ReadTimeout("slow")
        if failure == "connect":
            raise httpx.ConnectError("down")
        if failure == "garbage":
            return httpx.Response(200, json={"error": "x"})
        return httpx.Response(200, json=[{"index": 99, "score": 1.0}])

    caplog.set_level(logging.WARNING)
    async with _client(handler) as client:
        result, applied = await rerank_with_fallback(
            TEIReranker("http://r", client), "q", CANDS, top_n=2, log=LOG
        )
    assert applied is False
    assert [c.chunk_id.int for c in result] == [1, 2]
    assert any("fused order" in r.message for r in caplog.records)


async def test_successful_rerank_reports_applied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 1, "score": 0.7}])

    async with _client(handler) as client:
        result, applied = await rerank_with_fallback(
            TEIReranker("http://r", client), "q", CANDS, top_n=3, log=LOG
        )
    assert applied is True and [c.chunk_id.int for c in result] == [2]


async def test_noop_reranker_is_a_no_op() -> None:
    assert await NoopReranker().rerank("q", CANDS, top_n=2) == CANDS[:2]
    result, applied = await rerank_with_fallback(NoopReranker(), "q", CANDS, top_n=2, log=LOG)
    assert result == CANDS[:2] and applied is False


async def test_get_reranker_follows_settings() -> None:
    async with httpx.AsyncClient() as client:
        assert isinstance(get_reranker(_settings(), client), NoopReranker)
        assert isinstance(get_reranker(_settings(reranker_enabled=True), client), NoopReranker)
        assert isinstance(get_reranker(_settings(reranker_url="http://r"), client), NoopReranker)
        on = get_reranker(_settings(reranker_enabled=True, reranker_url="http://r"), client)
        assert isinstance(on, TEIReranker)
        slow = get_reranker(
            _settings(
                reranker_enabled=True, reranker_url="http://r", reranker_timeout_seconds=99.0
            ),
            client,
        )
        assert isinstance(slow, TEIReranker) and slow._timeout == 99.0
