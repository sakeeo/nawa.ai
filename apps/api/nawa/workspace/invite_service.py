import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.audit import record_audit
from nawa.core.errors import ConflictError, NotFoundError, ValidationFailedError
from nawa.core.security import hash_password, hash_token
from nawa.workspace import repository
from nawa.workspace.models import Membership, User
from nawa.workspace.schemas import InviteAccepted

INVALID_INVITE = "This invite is invalid, expired, or already used"


async def accept(session: AsyncSession, *, token: str, password: str | None) -> InviteAccepted:
    """Accept an invite. `session` must be a SystemSession (cross-tenant lookup).

    Everything runs in one transaction: if a password is missing for a new user the error is
    raised before commit, so the invite stays usable.
    """
    invite = await repository.consume_invite(session, hash_token(token), datetime.now(UTC))
    if invite is None:
        raise NotFoundError(INVALID_INVITE)

    user = await repository.get_user_by_email(session, invite.email)
    if user is None:
        if password is None:
            raise ValidationFailedError("A password is required to accept this invite")
        user = User(
            id=uuid.uuid4(),
            email=invite.email,
            password_hash=await asyncio.to_thread(hash_password, password),
            is_admin=False,
            is_active=True,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ConflictError("An account with this email already exists") from exc

    membership = await repository.get_membership(session, invite.workspace_id, user.id)
    if membership is None:
        session.add(
            Membership(
                id=uuid.uuid4(),
                workspace_id=invite.workspace_id,
                user_id=user.id,
                role=invite.role,
            )
        )
    else:
        membership.role = invite.role
    await record_audit(
        session,
        action="invite.accepted",
        actor_id=user.id,
        workspace_id=invite.workspace_id,
        target=invite.email,
    )
    await session.commit()
    return InviteAccepted(email=invite.email, workspace_id=invite.workspace_id, role=invite.role)
