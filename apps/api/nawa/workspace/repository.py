import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.workspace.models import Membership, RefreshToken, User, Workspace


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


async def get_workspace(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace | None:
    result = await session.execute(select(Workspace).where(Workspace.id == workspace_id))
    return result.scalar_one_or_none()


async def workspace_exists(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    return await get_workspace(session, workspace_id) is not None


async def list_workspaces(
    session: AsyncSession, *, user_id: uuid.UUID, is_admin: bool
) -> list[tuple[Workspace, str]]:
    if is_admin:
        result = await session.execute(select(Workspace).order_by(Workspace.name))
        return [(workspace, "admin") for workspace in result.scalars().all()]
    rows = await session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user_id)
        .order_by(Workspace.name)
    )
    return [(workspace, role) for workspace, role in rows.all()]


async def get_membership(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> Membership | None:
    result = await session.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_members(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[tuple[Membership, User]]:
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(User.email)
    )
    return [(membership, user) for membership, user in rows.all()]


async def delete_membership(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    result = await session.execute(
        delete(Membership)
        .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        .returning(Membership.id)
    )
    return result.first() is not None
