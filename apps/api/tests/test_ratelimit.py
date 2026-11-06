import fakeredis.aioredis

from nawa.core.ratelimit import RateLimiter


async def test_blocks_after_limit_and_resets() -> None:
    limiter = RateLimiter(fakeredis.aioredis.FakeRedis(), window_seconds=60)
    assert await limiter.is_blocked("k", limit=2) is False
    await limiter.hit("k")
    assert await limiter.is_blocked("k", limit=2) is False
    await limiter.hit("k")
    assert await limiter.is_blocked("k", limit=2) is True
    await limiter.reset("k")
    assert await limiter.is_blocked("k", limit=2) is False


async def test_keys_are_independent() -> None:
    limiter = RateLimiter(fakeredis.aioredis.FakeRedis(), window_seconds=60)
    await limiter.hit("a")
    await limiter.hit("a")
    assert await limiter.is_blocked("a", limit=2) is True
    assert await limiter.is_blocked("b", limit=2) is False


async def test_hit_sets_expiry() -> None:
    redis = fakeredis.aioredis.FakeRedis()
    limiter = RateLimiter(redis, window_seconds=60)
    await limiter.hit("k")
    assert 0 < await redis.ttl("k") <= 60
