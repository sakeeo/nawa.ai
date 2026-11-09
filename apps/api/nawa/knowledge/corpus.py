import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.db import apply_rls
from nawa.intelligence.gateway import LLMGateway
from nawa.knowledge import repository
from nawa.knowledge.extract import detect_kind
from nawa.knowledge.ingest import ingest_document
from nawa.knowledge.models import Document
from nawa.knowledge.storage import FileStorage

_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
}


@dataclass(frozen=True)
class CorpusResult:
    document_ids: dict[str, uuid.UUID]  # filename -> document id
    failed: dict[str, str]  # filename -> error message


async def load_documents(
    maker: async_sessionmaker[AsyncSession],
    gateway: LLMGateway,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    paths: list[Path],
    upload_dir: Path,
    chunker_name: str = "heading",
    replace: bool = False,
    max_pages: int = 200,
) -> CorpusResult:
    """Add local files to the workspace's default knowledge base and ingest them in-process.

    Used by the evaluation and by loading the demo documents. With `replace` the workspace's
    existing documents (and their chunks) are removed first.
    """
    storage = FileStorage(upload_dir)
    ids: dict[str, uuid.UUID] = {}
    async with maker() as session:
        await apply_rls(session, workspace_id=workspace_id, is_admin=True)
        if replace:
            old = await repository.list_documents(session, workspace_id)
            await session.execute(delete(Document).where(Document.workspace_id == workspace_id))
            for document in old:
                storage.delete(workspace_id, document.id)
        kb = await repository.get_or_create_default_kb(session, workspace_id)
        for path in paths:
            data = path.read_bytes()
            kind = detect_kind(data, path.name)
            document = Document(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                knowledge_base_id=kb.id,
                filename=path.name,
                mime=_MIME[kind],
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                status="queued",
                created_by=user_id,
            )
            session.add(document)
            storage.save(workspace_id, document.id, data)
            ids[path.name] = document.id
        await session.commit()
    failed: dict[str, str] = {}
    for document_id in ids.values():
        await ingest_document(
            maker,
            storage,
            gateway,
            workspace_id=workspace_id,
            document_id=document_id,
            chunker_name=chunker_name,
            max_pages=max_pages,
        )
    async with maker() as session:
        await apply_rls(session, workspace_id=workspace_id, is_admin=True)
        for document in await repository.list_documents(session, workspace_id):
            if document.status != "ready":
                failed[document.filename] = document.error or document.status
    return CorpusResult(ids, failed)
