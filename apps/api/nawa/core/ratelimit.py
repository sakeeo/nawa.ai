from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from nawa.core.config import Settings, get_settings


@lru_cache
def _client(url: str) -> Redis:
    return Redis.from_url(url)


def get_redis(settings: Annotated[Settings, Depends(get_settings)]) -> Redis:
    return _client(settings.redis_url)


class RateLimiter:
    """Fixed-window failure counter. The window starts at the first hit."""

    def __init__(self, redis: Redis, *, window_seconds: int) -> None:
        self._redis = redis
        self._window = window_seconds

    async def is_blocked(self, key: str, limit: int) -> bool:
        raw = await self._redis.get(key)
        return raw is not None and int(raw) >= limit

    async def hit(self, key: str) -> None:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, self._window, nx=True)
        await pipe.execute()

    async def reset(self, key: str) -> None:
        await self._redis.delete(key)


def get_limiter(
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RateLimiter:
    return RateLimiter(redis, window_seconds=settings.login_window_seconds)
