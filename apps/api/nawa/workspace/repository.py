import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.workspace.models import Membership, RefreshToken, User


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def list_memberships(session: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    result = await session.execute(
        select(Membership).where(Membership.user_id == user_id).order_by(Membership.created_at)
    )
    return list(result.scalars().all())


async def get_refresh_token_by_hash(
    session: AsyncSession, token_hash: str, *, for_update: bool = False
) -> RefreshToken | None:
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
