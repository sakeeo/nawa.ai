import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.db import apply_rls
from nawa.intelligence.gateway import LLMGateway, LLMUnavailableError
from nawa.knowledge.chunking import ChunkDraft, get_chunker
from nawa.knowledge.extract import (
    DocumentTooLargeError,
    UnsupportedDocumentError,
    detect_kind,
    extract_blocks,
)
from nawa.knowledge.models import EMBEDDING_DIM, Chunk, Document
from nawa.knowledge.normalize import normalize_blocks
from nawa.knowledge.storage import FileStorage

logger = logging.getLogger("nawa.knowledge.ingest")

EMBED_BATCH = 16
MAX_ERROR_CHARS = 300


class EmbeddingError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


_SAFE_ERRORS = (
    UnsupportedDocumentError,
    DocumentTooLargeError,
    EmbeddingError,
    EmptyDocumentError,
    LLMUnavailableError,
)


def describe_error(exc: Exception) -> str:
    """A short message that is safe to show: known errors keep their text, others only a class."""
    if isinstance(exc, _SAFE_ERRORS):
        detail = getattr(exc, "detail", None) or str(exc)
        return f"{type(exc).__name__}: {detail}"[:MAX_ERROR_CHARS]
    if isinstance(exc, FileNotFoundError):
        return "The stored file is missing; upload the document again."
    return f"Unexpected error ({type(exc).__name__})"


async def embed_in_batches(gateway: LLMGateway, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]
        result = await gateway.embed(batch)
        if len(result) != len(batch):
            raise EmbeddingError(f"Expected {len(batch)} embeddings, got {len(result)}")
        for vector in result:
            if len(vector) != EMBEDDING_DIM:
                raise EmbeddingError(
                    f"Embedding has {len(vector)} dimensions; expected {EMBEDDING_DIM}"
                )
        vectors.extend(result)
    return vectors


@dataclass(frozen=True)
class _Built:
    chunks: list[ChunkDraft]
    page_count: int | None


def build_chunks(data: bytes, filename: str, *, max_pages: int, chunker_name: str) -> _Built:
    kind = detect_kind(data, filename)
    try:
        raw_blocks = extract_blocks(data, kind, max_pages=max_pages)
    except (UnsupportedDocumentError, DocumentTooLargeError):
        raise
    except Exception as exc:  # parser libraries raise their own types on corrupt files
        raise UnsupportedDocumentError(
            f"The {kind.upper()} file could not be read; it may be corrupt."
        ) from exc
    blocks = normalize_blocks(raw_blocks)
    if not blocks:
        raise EmptyDocumentError("No extractable text found (scanned PDFs are not supported).")
    chunks = get_chunker(chunker_name).chunk(blocks)
    if not chunks:
        raise EmptyDocumentError("The document has no text content to index.")
    pages = [b.page for b in blocks if b.page is not None]
    return _Built(chunks, max(pages) if pages else None)


async def _set_status(
    maker: async_sessionmaker[AsyncSession],
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    status: str,
    error: str | None = None,
) -> Document | None:
    async with maker() as session:
        await apply_rls(session, workspace_id=workspace_id)
        document = await session.get(Document, document_id)
        if document is None or document.workspace_id != workspace_id:
            return None
        document.status = status
        document.error = error
        await session.commit()
        session.expunge(document)
        return document


async def ingest_document(
    maker: async_sessionmaker[AsyncSession],
    storage: FileStorage,
    gateway: LLMGateway,
    *,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    chunker_name: str = "heading",
    max_pages: int = 200,
) -> None:
    """Extract, chunk, embed and store one document. Idempotent; never raises on bad input.

    Any failure leaves the document `failed` with a short message and no partial chunk set,
    because the chunk replacement happens in a single transaction.
    """
    document = await _set_status(maker, workspace_id, document_id, "processing")
    if document is None:
        logger.warning("ingest skipped: document %s not found", document_id)
        return
    try:
        data = storage.read(workspace_id, document_id)
        built = build_chunks(
            data, document.filename, max_pages=max_pages, chunker_name=chunker_name
        )
        vectors = await embed_in_batches(gateway, [c.text for c in built.chunks])
        async with maker() as session:
            await apply_rls(session, workspace_id=workspace_id)
            current = await session.get(Document, document_id)
            if current is None:
                return
            await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            session.add_all(
                Chunk(
                    workspace_id=workspace_id,
                    document_id=document_id,
                    ordinal=draft.ordinal,
                    text=draft.text,
                    page=draft.page,
                    section_path=draft.section_path or None,
                    heading=draft.heading,
                    token_count=draft.token_count,
                    embedding=vector,
                )
                for draft, vector in zip(built.chunks, vectors, strict=True)
            )
            current.status = "ready"
            current.error = None
            current.page_count = built.page_count
            await session.commit()
        logger.info("ingested document %s: %d chunks", document_id, len(built.chunks))
    except Exception as exc:
        logger.warning("ingest failed for document %s: %s", document_id, type(exc).__name__)
        await _set_status(maker, workspace_id, document_id, "failed", describe_error(exc))
