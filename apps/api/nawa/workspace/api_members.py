import uuid

from fastapi import APIRouter, Depends, Response

from nawa.core.audit import record_audit
from nawa.core.errors import NotFoundError
from nawa.workspace import repository
from nawa.workspace.deps import ManagerCtx, ViewerCtx, require_csrf
from nawa.workspace.schemas import MemberOut, MemberUpdate

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/members",
    tags=["members"],
    dependencies=[Depends(require_csrf)],
)


@router.get("", response_model=list[MemberOut])
async def list_members(ctx: ViewerCtx) -> list[MemberOut]:
    rows = await repository.list_members(ctx.session, ctx.workspace_id)
    return [MemberOut(user_id=user.id, email=user.email, role=m.role) for m, user in rows]


@router.patch("/{user_id}", response_model=MemberOut)
async def update_member(user_id: uuid.UUID, body: MemberUpdate, ctx: ManagerCtx) -> MemberOut:
    membership = await repository.get_membership(ctx.session, ctx.workspace_id, user_id)
    user = await repository.get_user(ctx.session, user_id)
    if membership is None or user is None:
        raise NotFoundError("Member not found")
    membership.role = body.role
    await record_audit(
        ctx.session,
        action="member.role_changed",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=str(user_id),
    )
    await ctx.session.commit()
    return MemberOut(user_id=user_id, email=user.email, role=body.role)


@router.delete("/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, ctx: ManagerCtx) -> Response:
    removed = await repository.delete_membership(ctx.session, ctx.workspace_id, user_id)
    if not removed:
        raise NotFoundError("Member not found")
    await record_audit(
        ctx.session,
        action="member.removed",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=str(user_id),
    )
    await ctx.session.commit()
    return Response(status_code=204)
