import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.knowledge.models import Chunk, Document, KnowledgeBase

DEFAULT_KB_NAME = "Default"


async def get_default_kb(session: AsyncSession, workspace_id: uuid.UUID) -> KnowledgeBase | None:
    result = await session.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == workspace_id)
        .order_by(KnowledgeBase.created_at, KnowledgeBase.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_or_create_default_kb(session: AsyncSession, workspace_id: uuid.UUID) -> KnowledgeBase:
    """The workspace's knowledge base, created on first use. Serialized per workspace."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"kb:{workspace_id}"},
    )
    kb = await get_default_kb(session, workspace_id)
    if kb is None:
        kb = KnowledgeBase(workspace_id=workspace_id, name=DEFAULT_KB_NAME)
        session.add(kb)
        await session.flush()
    return kb


async def find_document_by_hash(
    session: AsyncSession, workspace_id: uuid.UUID, knowledge_base_id: uuid.UUID, sha256: str
) -> Document | None:
    result = await session.execute(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.knowledge_base_id == knowledge_base_id,
            Document.sha256 == sha256,
        )
    )
    return result.scalar_one_or_none()


async def list_documents(session: AsyncSession, workspace_id: uuid.UUID) -> list[Document]:
    result = await session.execute(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc(), Document.id)
    )
    return list(result.scalars().all())


async def get_document(
    session: AsyncSession, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    result = await session.execute(
        select(Document).where(Document.workspace_id == workspace_id, Document.id == document_id)
    )
    return result.scalar_one_or_none()


async def delete_document(
    session: AsyncSession, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> bool:
    result = await session.execute(
        delete(Document).where(Document.workspace_id == workspace_id, Document.id == document_id)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def get_chunk_with_filename(
    session: AsyncSession, workspace_id: uuid.UUID, chunk_id: uuid.UUID
) -> tuple[Chunk, str] | None:
    result = await session.execute(
        select(Chunk, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.workspace_id == workspace_id, Chunk.id == chunk_id)
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row else None
