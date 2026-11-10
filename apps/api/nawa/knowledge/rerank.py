import logging
from dataclasses import replace
from typing import Protocol

import httpx

from nawa.core.config import Settings
from nawa.knowledge.retrieval import Candidate

RERANK_TIMEOUT = 10.0


class RerankerError(RuntimeError):
    pass


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_n: int
    ) -> list[Candidate]: ...


class NoopReranker:
    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_n: int
    ) -> list[Candidate]:
        return candidates[:top_n]


class TEIReranker:
    """Cross-encoder reranking through a Hugging Face text-embeddings-inference `/rerank`."""

    def __init__(
        self, url: str, client: httpx.AsyncClient, *, timeout: float = RERANK_TIMEOUT
    ) -> None:
        self._url = url.rstrip("/") + "/rerank"
        self._client = client
        self._timeout = timeout

    async def rerank(
        self, query: str, candidates: list[Candidate], *, top_n: int
    ) -> list[Candidate]:
        if not candidates:
            return []
        response = await self._client.post(
            self._url,
            json={"query": query, "texts": [c.text for c in candidates], "truncate": True},
            timeout=self._timeout,
        )
        response.raise_for_status()
        try:
            ranked = [(int(r["index"]), float(r["score"])) for r in response.json()]
            if any(not 0 <= i < len(candidates) for i, _ in ranked):
                raise ValueError("index out of range")
        except (ValueError, KeyError, TypeError) as exc:
            raise RerankerError(f"unexpected reranker response: {exc}") from exc
        ranked.sort(key=lambda r: (-r[1], r[0]))
        return [replace(candidates[i], rerank_score=score) for i, score in ranked[:top_n]]


async def rerank_with_fallback(
    reranker: Reranker,
    query: str,
    candidates: list[Candidate],
    *,
    top_n: int,
    log: logging.Logger,
) -> tuple[list[Candidate], bool]:
    """Rerank; on any failure keep the fused order. The flag says whether reranking was applied."""
    if not candidates:
        return [], False
    try:
        reranked = await reranker.rerank(query, candidates, top_n=top_n)
    except (httpx.HTTPError, RerankerError) as exc:
        log.warning("reranker unavailable, using fused order: %s", type(exc).__name__)
        return candidates[:top_n], False
    return reranked, not isinstance(reranker, NoopReranker)


def get_reranker(settings: Settings, client: httpx.AsyncClient) -> Reranker:
    if settings.reranker_enabled and settings.reranker_url:
        return TEIReranker(settings.reranker_url, client, timeout=settings.reranker_timeout_seconds)
    return NoopReranker()
