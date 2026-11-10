import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.knowledge.models import (
    Chunk,
    Citation,
    Conversation,
    Document,
    Feedback,
    KnowledgeBase,
    Message,
)

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


async def create_conversation(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, title: str
) -> Conversation:
    conversation = Conversation(workspace_id=workspace_id, user_id=user_id, title=title)
    session.add(conversation)
    await session.flush()
    return conversation


async def get_conversation(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(
            Conversation.workspace_id == workspace_id,
            Conversation.user_id == user_id,
            Conversation.id == conversation_id,
        )
    )
    return result.scalar_one_or_none()


async def list_conversations(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> list[tuple[Conversation, datetime]]:
    last = func.coalesce(func.max(Message.created_at), Conversation.created_at)
    result = await session.execute(
        select(Conversation, last)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.workspace_id == workspace_id, Conversation.user_id == user_id)
        .group_by(Conversation.id)
        .order_by(last.desc(), Conversation.id)
    )
    return [(row[0], row[1]) for row in result]


async def add_message(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    *,
    message_id: uuid.UUID | None = None,
    **extra: Any,
) -> Message:
    message = Message(
        id=message_id or uuid.uuid4(),
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        **extra,
    )
    session.add(message)
    await session.flush()
    return message


async def list_messages(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[tuple[Message, list[tuple[Citation, Chunk, str]], int | None]]:
    """Messages in order with their citations (and the caller's feedback value)."""
    messages = (
        (
            await session.execute(
                select(Message)
                .where(
                    Message.workspace_id == workspace_id, Message.conversation_id == conversation_id
                )
                .order_by(Message.created_at, Message.role.desc())
            )
        )
        .scalars()
        .all()
    )
    ids = [m.id for m in messages]
    cites: dict[uuid.UUID, list[tuple[Citation, Chunk, str]]] = {}
    feedback: dict[uuid.UUID, int] = {}
    if ids:
        rows = await session.execute(
            select(Citation, Chunk, Document.filename)
            .join(Chunk, Chunk.id == Citation.chunk_id)
            .join(Document, Document.id == Chunk.document_id)
            .where(Citation.message_id.in_(ids))
            .order_by(Citation.marker)
        )
        for citation, chunk, filename in rows:
            cites.setdefault(citation.message_id, []).append((citation, chunk, filename))
        fb = await session.execute(
            select(Feedback.message_id, Feedback.value).where(
                Feedback.message_id.in_(ids), Feedback.user_id == user_id
            )
        )
        feedback = {row[0]: row[1] for row in fb}
    return [(m, cites.get(m.id, []), feedback.get(m.id)) for m in messages]


async def get_own_assistant_message(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, message_id: uuid.UUID
) -> Message | None:
    result = await session.execute(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.workspace_id == workspace_id,
            Message.id == message_id,
            Message.role == "assistant",
            Conversation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_feedback(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    value: int,
    comment: str | None,
) -> None:
    statement = pg_insert(Feedback).values(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        message_id=message_id,
        user_id=user_id,
        value=value,
        comment=comment,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_feedback_message_user",
            set_={"value": value, "comment": comment},
        )
    )
