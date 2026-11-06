import uuid
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from nawa.core.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def _engine_for(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def get_sessionmaker(
    settings: Annotated[Settings, Depends(get_settings)],
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine_for(settings.database_url), expire_on_commit=False)


async def get_session(
    maker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
) -> AsyncIterator[AsyncSession]:
    """One session per request. Callers commit explicitly; leaving without commit rolls back."""
    async with maker() as session:
        yield session


async def apply_rls(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    is_admin: bool = False,
) -> None:
    """Set the transaction-local settings that Row-Level Security policies read.

    The values are reset when the transaction ends, so call this before the queries and
    commit last.
    """
    await session.execute(
        text(
            "SELECT set_config('app.workspace_id', :workspace_id, true),"
            " set_config('app.user_id', :user_id, true),"
            " set_config('app.is_admin', :is_admin, true)"
        ),
        {
            "workspace_id": str(workspace_id) if workspace_id else "",
            "user_id": str(user_id) if user_id else "",
            "is_admin": "true" if is_admin else "false",
        },
    )
