"""Approved questions as few-shot examples (SHOULD feature of phase 2).

A thumbs-up on a successful answer stores the question and the guarded SQL with an embedding.
At ask time the nearest approved questions of the same data source go into the prompt, inside
an untrusted block (they came from users). Everything here is best effort: an embedding failure
means no example, never a failed question.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.data.models import ApprovedQuery, QueryLog
from nawa.intelligence.gateway import LLMGateway

logger = logging.getLogger("nawa.data.fewshot")

MIN_SIMILARITY = 0.75
DEFAULT_K = 3


async def _embed(gateway: LLMGateway, text: str) -> list[float] | None:
    try:
        vector = (await gateway.embed([text]))[0]
    except Exception:
        logger.warning("Embedding failed; skipping the few-shot step", exc_info=True)
        return None
    return vector if any(vector) else None


async def approve_query(
    session: AsyncSession,
    gateway: LLMGateway,
    *,
    entry: QueryLog,
    approved_by: uuid.UUID | None,
) -> bool:
    """Store `entry` as an example. Only a successful query with SQL and a source qualifies."""
    if entry.status != "ok" or not entry.sql or entry.data_source_id is None:
        return False
    question = entry.question.strip()
    vector = await _embed(gateway, question)
    if vector is None:
        return False
    statement = pg_insert(ApprovedQuery).values(
        workspace_id=entry.workspace_id,
        data_source_id=entry.data_source_id,
        question=question,
        sql=entry.sql,
        embedding=vector,
        approved_by=approved_by,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_approved_queries_source_question",
            set_={
                "sql": statement.excluded.sql,
                "embedding": statement.excluded.embedding,
                "approved_by": statement.excluded.approved_by,
                "created_at": datetime.now(UTC),
            },
        )
    )
    return True


async def unapprove_query(
    session: AsyncSession, workspace_id: uuid.UUID, source_id: uuid.UUID, question: str
) -> bool:
    result = await session.execute(
        delete(ApprovedQuery)
        .where(
            ApprovedQuery.workspace_id == workspace_id,
            ApprovedQuery.data_source_id == source_id,
            ApprovedQuery.question == question.strip(),
        )
        .returning(ApprovedQuery.id)
    )
    return result.first() is not None


async def similar_examples(
    session: AsyncSession,
    gateway: LLMGateway,
    *,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    question: str,
    k: int = DEFAULT_K,
    min_similarity: float = MIN_SIMILARITY,
) -> list[tuple[str, str]]:
    """The nearest approved (question, SQL) pairs of this source, most similar first."""
    vector = await _embed(gateway, question.strip())
    if vector is None:
        return []
    distance = ApprovedQuery.embedding.cosine_distance(vector)
    rows = await session.execute(
        select(ApprovedQuery.question, ApprovedQuery.sql, distance.label("distance"))
        .where(
            ApprovedQuery.workspace_id == workspace_id, ApprovedQuery.data_source_id == source_id
        )
        .order_by(distance)
        .limit(k)
    )
    return [(q, sql) for q, sql, d in rows if 1 - float(d) >= min_similarity]
