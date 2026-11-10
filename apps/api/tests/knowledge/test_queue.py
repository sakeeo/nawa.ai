import uuid
from typing import Any

from arq.connections import RedisSettings

from nawa.core.config import Settings
from nawa.knowledge.queue import INGEST_FUNCTION, arq_redis_settings, enqueue_ingest


class FakePool:
    """Mimics ARQ: a second enqueue with the same _job_id returns None (no new job)."""

    def __init__(self) -> None:
        self.jobs: dict[str, tuple[str, tuple[Any, ...]]] = {}
        self.closed = False

    async def enqueue_job(self, function: str, *args: Any, _job_id: str, **_: Any) -> object | None:
        if _job_id in self.jobs:
            return None
        self.jobs[_job_id] = (function, args)
        return object()

    async def aclose(self) -> None:
        self.closed = True


def _settings(url: str) -> Settings:
    return Settings(_env_file=None, database_url="x", redis_url=url, jwt_secret="s" * 32)


def test_arq_redis_settings_parses_url() -> None:
    parsed = arq_redis_settings(_settings("redis://cache:6380/2"))
    assert isinstance(parsed, RedisSettings)
    assert (parsed.host, parsed.port, parsed.database) == ("cache", 6380, 2)


async def test_enqueue_twice_yields_one_job() -> None:
    pool = FakePool()
    ws, doc = uuid.uuid4(), uuid.uuid4()
    settings = arq_redis_settings(_settings("redis://redis:6379/0"))
    await enqueue_ingest(settings, ws, doc, pool=pool)
    await enqueue_ingest(settings, ws, doc, pool=pool)
    assert pool.jobs == {str(doc): (INGEST_FUNCTION, (str(ws), str(doc)))}
    assert not pool.closed  # a caller-supplied pool is not closed here
