"""ARQ worker. Runs as the restricted app role and applies RLS per job (decision P5)."""

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nawa.core.config import get_settings
from nawa.intelligence.gateway import LiteLLMClient, LLMGateway
from nawa.knowledge.ingest import ingest_document
from nawa.knowledge.queue import arq_redis_settings
from nawa.knowledge.storage import FileStorage

_settings = get_settings()


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["sessionmaker"] = async_sessionmaker(engine, expire_on_commit=False)
    ctx["storage"] = FileStorage(Path(settings.upload_dir))
    # Ingestion only embeds, and embeddings are always local; the chat model is unused here.
    ctx["gateway"] = LLMGateway(LiteLLMClient(), settings, model=settings.local_llm_model)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def ingest_job(ctx: dict[str, Any], workspace_id: str, document_id: str) -> None:
    await ingest_document(
        ctx["sessionmaker"],
        ctx["storage"],
        ctx["gateway"],
        workspace_id=uuid.UUID(workspace_id),
        document_id=uuid.UUID(document_id),
        max_pages=ctx["settings"].max_pdf_pages,
    )


class WorkerSettings:
    functions = [ingest_job]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = arq_redis_settings(_settings)
    max_jobs = 2
    job_timeout = 900
    max_tries = 3
