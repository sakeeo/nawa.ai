import hashlib
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.audit import record_audit
from nawa.core.db import apply_rls, get_sessionmaker
from nawa.core.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    UnsupportedMediaTypeError,
    ValidationFailedError,
)
from nawa.core.ratelimit import RateLimiter, get_redis
from nawa.intelligence.deps import get_llm_client, model_for_provider
from nawa.intelligence.gateway import LLMClient, LLMGateway
from nawa.knowledge import repository
from nawa.knowledge.chat_service import stream_chat
from nawa.knowledge.extract import UnsupportedDocumentError, detect_kind
from nawa.knowledge.guardrails import sanitize_question
from nawa.knowledge.models import Document
from nawa.knowledge.queue import arq_redis_settings, enqueue_ingest
from nawa.knowledge.schemas import (
    ChatRequest,
    ChunkOut,
    CitationOut,
    ConversationDetail,
    ConversationOut,
    DocumentOut,
    FeedbackIn,
    MessageOut,
)
from nawa.knowledge.storage import FileStorage
from nawa.workspace import repository as workspace_repository
from nawa.workspace.deps import ManagerCtx, MemberCtx, SettingsDep, ViewerCtx, require_csrf

logger = logging.getLogger("nawa.knowledge.api")

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}",
    tags=["knowledge"],
    dependencies=[Depends(require_csrf)],
)

MIME_BY_KIND = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}

EnqueueFn = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]


def get_storage(settings: SettingsDep) -> FileStorage:
    return FileStorage(Path(settings.upload_dir))


def get_redis_settings(settings: SettingsDep) -> RedisSettings:
    return arq_redis_settings(settings)


def get_enqueue(redis_settings: Annotated[RedisSettings, Depends(get_redis_settings)]) -> EnqueueFn:
    async def enqueue(workspace_id: uuid.UUID, document_id: uuid.UUID) -> None:
        await enqueue_ingest(redis_settings, workspace_id, document_id)

    return enqueue


StorageDep = Annotated[FileStorage, Depends(get_storage)]
EnqueueDep = Annotated[EnqueueFn, Depends(get_enqueue)]

QUEUE_FAILED = "Could not queue ingestion. Use retry once the queue is available."


def _clean_filename(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:255] or "document"


def _out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        mime=document.mime,
        size_bytes=document.size_bytes,
        status=document.status,
        error=document.error,
        page_count=document.page_count,
        created_at=document.created_at,
    )


async def _reapply_rls(ctx: ManagerCtx) -> None:
    """RLS settings last one transaction; call this again after a commit before more queries."""
    await apply_rls(
        ctx.session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        is_admin=ctx.user.is_admin,
    )


async def _queue(enqueue: EnqueueFn, ctx: ManagerCtx, document: Document) -> None:
    """Queue ingestion; if the queue is down, mark the document failed instead of stuck."""
    try:
        await enqueue(ctx.workspace_id, document.id)
    except Exception:
        logger.exception("could not enqueue document %s", document.id)
        await _reapply_rls(ctx)
        document.status = "failed"
        document.error = QUEUE_FAILED
        await ctx.session.commit()


@router.post("/documents", response_model=DocumentOut, status_code=202)
async def upload_document(
    ctx: ManagerCtx,
    settings: SettingsDep,
    storage: StorageDep,
    enqueue: EnqueueDep,
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"The file exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit."
        )
    if not data:
        raise ValidationFailedError("The file is empty.")
    filename = _clean_filename(file.filename)
    try:
        kind = detect_kind(data, filename)
    except UnsupportedDocumentError as exc:
        raise UnsupportedMediaTypeError(str(exc)) from exc

    sha256 = hashlib.sha256(data).hexdigest()
    session = ctx.session
    kb = await repository.get_or_create_default_kb(session, ctx.workspace_id)
    existing = await repository.find_document_by_hash(session, ctx.workspace_id, kb.id, sha256)
    if existing is not None:
        raise ConflictError(f"This file is already uploaded (document {existing.id}).")

    document = Document(
        id=uuid.uuid4(),
        workspace_id=ctx.workspace_id,
        knowledge_base_id=kb.id,
        filename=filename,
        mime=MIME_BY_KIND[kind],
        size_bytes=len(data),
        sha256=sha256,
        status="queued",
        created_by=ctx.user.id,
    )
    session.add(document)
    await record_audit(
        session,
        action="document.uploaded",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=str(document.id),
    )
    storage.save(ctx.workspace_id, document.id, data)
    try:
        await session.commit()
    except IntegrityError as exc:
        storage.delete(ctx.workspace_id, document.id)
        raise ConflictError("This file is already uploaded.") from exc
    await _reapply_rls(ctx)
    await session.refresh(document)
    await _queue(enqueue, ctx, document)
    return _out(document)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(ctx: ViewerCtx) -> list[DocumentOut]:
    return [_out(d) for d in await repository.list_documents(ctx.session, ctx.workspace_id)]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, ctx: ViewerCtx) -> DocumentOut:
    document = await repository.get_document(ctx.session, ctx.workspace_id, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    return _out(document)


@router.post("/documents/{document_id}/retry", response_model=DocumentOut, status_code=202)
async def retry_document(
    document_id: uuid.UUID, ctx: ManagerCtx, enqueue: EnqueueDep
) -> DocumentOut:
    document = await repository.get_document(ctx.session, ctx.workspace_id, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    if document.status != "failed":
        raise ConflictError("Only failed documents can be retried.")
    document.status = "queued"
    document.error = None
    await ctx.session.commit()
    await _reapply_rls(ctx)
    await ctx.session.refresh(document)
    await _queue(enqueue, ctx, document)
    return _out(document)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, ctx: ManagerCtx, storage: StorageDep) -> Response:
    if not await repository.delete_document(ctx.session, ctx.workspace_id, document_id):
        raise NotFoundError("Document not found")
    await record_audit(
        ctx.session,
        action="document.deleted",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=str(document_id),
    )
    await ctx.session.commit()
    storage.delete(ctx.workspace_id, document_id)
    return Response(status_code=204)


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def get_chunk(chunk_id: uuid.UUID, ctx: ViewerCtx) -> ChunkOut:
    found = await repository.get_chunk_with_filename(ctx.session, ctx.workspace_id, chunk_id)
    if found is None:
        raise NotFoundError("Chunk not found")
    chunk, filename = found
    return ChunkOut(
        id=chunk.id,
        document_id=chunk.document_id,
        filename=filename,
        page=chunk.page,
        section_path=chunk.section_path,
        heading=chunk.heading,
        text=chunk.text,
    )


TITLE_CHARS = 60


@router.post("/chat")
async def chat(
    body: ChatRequest,
    ctx: MemberCtx,
    settings: SettingsDep,
    client: Annotated[LLMClient, Depends(get_llm_client)],
    maker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StreamingResponse:
    question = sanitize_question(body.question)
    if not question:
        raise ValidationFailedError("The question is empty.")
    limiter = RateLimiter(redis, window_seconds=60)
    key = f"chat:{ctx.user.id}"
    if await limiter.is_blocked(key, settings.chat_limit_per_minute):
        raise RateLimitedError("Too many questions. Try again in a minute.")
    await limiter.hit(key)

    session = ctx.session
    instance = await workspace_repository.get_instance_settings(session)
    if not instance.setup_completed or instance.ai_provider is None:
        raise ConflictError("Setup has not been completed")
    if body.conversation_id is None:
        title = question if len(question) <= TITLE_CHARS else question[: TITLE_CHARS - 1] + "…"
        conversation = await repository.create_conversation(
            session, ctx.workspace_id, ctx.user.id, title
        )
    else:
        found = await repository.get_conversation(
            session, ctx.workspace_id, ctx.user.id, body.conversation_id
        )
        if found is None:
            raise NotFoundError("Conversation not found")
        conversation = found
    conversation_id = conversation.id
    await repository.add_message(session, ctx.workspace_id, conversation_id, "user", question)
    await session.commit()

    gateway = LLMGateway(client, settings, model=model_for_provider(settings, instance.ai_provider))
    stream = stream_chat(
        maker=maker,
        gateway=gateway,
        settings=settings,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        is_admin=ctx.user.is_admin,
        conversation_id=conversation_id,
        message_id=uuid.uuid4(),
        question=question,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(ctx: MemberCtx) -> list[ConversationOut]:
    rows = await repository.list_conversations(ctx.session, ctx.workspace_id, ctx.user.id)
    return [
        ConversationOut(id=c.id, title=c.title, created_at=c.created_at, last_message_at=last)
        for c, last in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, ctx: MemberCtx) -> ConversationDetail:
    conversation = await repository.get_conversation(
        ctx.session, ctx.workspace_id, ctx.user.id, conversation_id
    )
    if conversation is None:
        raise NotFoundError("Conversation not found")
    rows = await repository.list_messages(
        ctx.session, ctx.workspace_id, ctx.user.id, conversation_id
    )
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                refused=m.refused,
                created_at=m.created_at,
                feedback=feedback,
                citations=[
                    CitationOut(
                        marker=c.marker,
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        filename=filename,
                        page=chunk.page,
                        section_path=chunk.section_path,
                    )
                    for c, chunk, filename in cites
                ],
            )
            for m, cites, feedback in rows
        ],
    )


@router.post("/messages/{message_id}/feedback", status_code=204)
async def give_feedback(message_id: uuid.UUID, body: FeedbackIn, ctx: MemberCtx) -> Response:
    message = await repository.get_own_assistant_message(
        ctx.session, ctx.workspace_id, ctx.user.id, message_id
    )
    if message is None:
        raise NotFoundError("Message not found")
    await repository.upsert_feedback(
        ctx.session, ctx.workspace_id, message_id, ctx.user.id, body.value, body.comment
    )
    await ctx.session.commit()
    return Response(status_code=204)
