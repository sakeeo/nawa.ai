from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nawa.core.config import Settings, get_settings

ReadinessCheck = Callable[[], Awaitable[None]]

router = APIRouter()


def get_readiness_checks(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, ReadinessCheck]:
    async def check_postgres() -> None:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    async def check_redis() -> None:
        client = Redis.from_url(settings.redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()

    return {"postgres": check_postgres, "redis": check_redis}


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    checks: Annotated[dict[str, ReadinessCheck], Depends(get_readiness_checks)],
) -> JSONResponse:
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            await check()
            results[name] = "ok"
        except Exception:
            results[name] = "failed"
    ready = all(value == "ok" for value in results.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": results},
    )
