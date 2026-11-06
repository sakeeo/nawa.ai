import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from nawa.core.audit import record_audit
from nawa.core.errors import NotFoundError
from nawa.core.security import hash_token, new_token
from nawa.workspace import invite_service, repository
from nawa.workspace.deps import AdminCtx, SettingsDep, SystemSession, require_csrf
from nawa.workspace.models import Invite
from nawa.workspace.schemas import (
    InviteAccept,
    InviteAccepted,
    InviteCreate,
    InviteCreated,
    InvitePreview,
)

workspace_router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/invites",
    tags=["invites"],
    dependencies=[Depends(require_csrf)],
)
public_router = APIRouter(prefix="/api/v1/invites", tags=["invites"])


@workspace_router.post("", status_code=201, response_model=InviteCreated)
async def create_invite(body: InviteCreate, ctx: AdminCtx, settings: SettingsDep) -> InviteCreated:
    raw_token = new_token()
    invite = Invite(
        id=uuid.uuid4(),
        email=body.email.lower(),
        token_hash=hash_token(raw_token),
        workspace_id=ctx.workspace_id,
        role=body.role,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.invite_ttl_seconds),
        created_by=ctx.user.id,
    )
    ctx.session.add(invite)
    await record_audit(
        ctx.session,
        action="invite.created",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=invite.email,
    )
    await ctx.session.commit()
    return InviteCreated(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        token=raw_token,
        accept_path=f"/invite/{raw_token}",
    )


@public_router.get("/{token}", response_model=InvitePreview)
async def preview_invite(token: str, session: SystemSession) -> InvitePreview:
    found = await repository.get_valid_invite(session, hash_token(token), datetime.now(UTC))
    if found is None:
        raise NotFoundError(invite_service.INVALID_INVITE)
    invite, workspace = found
    return InvitePreview(email=invite.email, workspace_name=workspace.name, role=invite.role)


@public_router.post("/accept", response_model=InviteAccepted)
async def accept_invite(body: InviteAccept, session: SystemSession) -> InviteAccepted:
    return await invite_service.accept(session, token=body.token, password=body.password)
