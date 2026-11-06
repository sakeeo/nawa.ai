import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.workspace.models import Membership, User


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
