import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.config import Settings
from nawa.intelligence.gateway import LLMGateway

Strategy = Literal["hybrid", "vector", "keyword"]

STOPWORDS = frozenset(
    """
    yang dan di ke dari untuk pada dengan atau adalah itu ini apa siapa bagaimana kapan dimana
    mengapa kenapa berapa apakah ada akan dalam oleh sebagai saya kami kita anda para juga
    sudah belum bisa dapat harus the a an of to in on for and or is are was were be what who
    how when where why which do does did with by as at from this that it
    """.split()
)
_TOKEN = re.compile(r"[^\W_]{2,}", re.UNICODE)


@dataclass(frozen=True)
class Candidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page: int | None
    section_path: str
    heading: str | None
    text: str
    similarity: float
    vector_rank: int | None
    keyword_rank: int | None
    rrf_score: float
    rerank_score: float | None = None


def rrf_fuse(
    vector_ids: list[uuid.UUID], keyword_ids: list[uuid.UUID], *, k: int = 60
) -> list[tuple[uuid.UUID, float, int | None, int | None]]:
    """Reciprocal Rank Fusion. Returns (id, score, vector_rank, keyword_rank), best first.

    Ranks are 1-based; a duplicate id in one list is dropped before ranking. Ties are
    broken by the better single rank, then by id, so the order is deterministic.
    """

    def ranks(ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        return {chunk_id: position for position, chunk_id in enumerate(dict.fromkeys(ids), 1)}

    vector, keyword = ranks(vector_ids), ranks(keyword_ids)
    rows = []
    for chunk_id in vector.keys() | keyword.keys():
        v, kw = vector.get(chunk_id), keyword.get(chunk_id)
        score = sum(1 / (k + r) for r in (v, kw) if r is not None)
        best = min(r for r in (v, kw) if r is not None)
        rows.append((chunk_id, score, v, kw, best))
    rows.sort(key=lambda r: (-r[1], r[4], str(r[0])))
    return [(cid, score, v, kw) for cid, score, v, kw, _ in rows]


def build_keyword_query(question: str) -> str | None:
    """A tsquery of OR-ed plain tokens. Only letters and digits survive, so no operators."""
    seen: dict[str, None] = {}
    for token in _TOKEN.findall(question.lower()):
        if token not in STOPWORDS:
            seen.setdefault(token)
    return " | ".join(seen) if seen else None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


async def vector_search(
    session: AsyncSession, query_vector: list[float], *, limit: int
) -> list[tuple[uuid.UUID, float]]:
    result = await session.execute(
        text(
            "SELECT c.id, 1 - (c.embedding <=> CAST(:v AS vector)) AS similarity"
            " FROM chunks c JOIN documents d ON d.id = c.document_id"
            " WHERE d.status = 'ready' AND c.embedding IS NOT NULL"
            " ORDER BY c.embedding <=> CAST(:v AS vector), c.id LIMIT :n"
        ),
        {"v": _vector_literal(query_vector), "n": limit},
    )
    return [(row[0], float(row[1])) for row in result]


async def keyword_search(session: AsyncSession, tsquery: str, *, limit: int) -> list[uuid.UUID]:
    result = await session.execute(
        text(
            "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id,"
            " to_tsquery('simple', :q) AS query"
            " WHERE d.status = 'ready' AND c.tsv @@ query"
            " ORDER BY ts_rank_cd(c.tsv, query) DESC, c.id LIMIT :n"
        ),
        {"q": tsquery, "n": limit},
    )
    return [row[0] for row in result]


async def _hydrate(
    session: AsyncSession, ids: list[uuid.UUID], query_vector: list[float] | None
) -> dict[uuid.UUID, tuple[object, ...]]:
    if not ids:
        return {}
    similarity = "1 - (c.embedding <=> CAST(:v AS vector))" if query_vector else "0.0"
    statement = text(
        f"SELECT c.id, c.document_id, d.filename, c.page, c.section_path, c.heading, c.text,"  # noqa: S608
        f" {similarity} AS similarity"
        " FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    params: dict[str, object] = {"ids": ids}
    if query_vector:
        params["v"] = _vector_literal(query_vector)
    return {row[0]: tuple(row) for row in await session.execute(statement, params)}


async def retrieve(
    session: AsyncSession,
    gateway: LLMGateway,
    question: str,
    *,
    settings: Settings,
    strategy: Strategy = "hybrid",
) -> list[Candidate]:
    """Top candidates for a question. RLS on the session is the only tenant filter."""
    query_vector: list[float] | None = None
    vector_hits: list[tuple[uuid.UUID, float]] = []
    keyword_ids: list[uuid.UUID] = []
    if strategy in ("hybrid", "vector"):
        query_vector = (await gateway.embed([question]))[0]
        vector_hits = await vector_search(session, query_vector, limit=settings.rag_vector_k)
    if strategy in ("hybrid", "keyword"):
        tsquery = build_keyword_query(question)
        if tsquery:
            keyword_ids = await keyword_search(session, tsquery, limit=settings.rag_keyword_k)
    fused = rrf_fuse([i for i, _ in vector_hits], keyword_ids, k=settings.rag_rrf_k)
    fused = fused[: settings.rag_final_k]
    rows = await _hydrate(session, [f[0] for f in fused], query_vector)
    candidates = []
    for chunk_id, score, v_rank, k_rank in fused:
        row = rows.get(chunk_id)
        if row is None:
            continue
        candidates.append(
            Candidate(
                chunk_id=chunk_id,
                document_id=row[1],  # type: ignore[arg-type]
                filename=row[2],  # type: ignore[arg-type]
                page=row[3],  # type: ignore[arg-type]
                section_path=row[4] or "",  # type: ignore[arg-type]
                heading=row[5],  # type: ignore[arg-type]
                text=row[6],  # type: ignore[arg-type]
                similarity=float(row[7]),  # type: ignore[arg-type]
                vector_rank=v_rank,
                keyword_rank=k_rank,
                rrf_score=score,
            )
        )
    return candidates
