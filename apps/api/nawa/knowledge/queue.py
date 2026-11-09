import uuid
from typing import Any, Protocol

from arq import create_pool
from arq.connections import RedisSettings

from nawa.core.config import Settings

INGEST_FUNCTION = "ingest_job"


class EnqueuePool(Protocol):
    async def enqueue_job(self, function: str, *args: Any, _job_id: str, **kwargs: Any) -> Any: ...

    async def aclose(self) -> None: ...


def arq_redis_settings(settings: Settings) -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def enqueue_ingest(
    redis_settings: RedisSettings,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    pool: EnqueuePool | None = None,
) -> None:
    """Queue ingestion of one document. The document id is the job id, so duplicates are no-ops."""
    owned = pool is None
    active = pool if pool is not None else await create_pool(redis_settings)
    try:
        await active.enqueue_job(
            INGEST_FUNCTION, str(workspace_id), str(document_id), _job_id=str(document_id)
        )
    finally:
        if owned:
            await active.aclose()
