import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError

from nawa.core.audit import record_audit
from nawa.core.errors import ConflictError, NotFoundError
from nawa.workspace import repository
from nawa.workspace.deps import AdminUser, CurrentUser, UserSession, ViewerCtx, require_csrf
from nawa.workspace.models import Workspace
from nawa.workspace.schemas import WorkspaceCreate, WorkspaceOut

router = APIRouter(
    prefix="/api/v1/workspaces", tags=["workspaces"], dependencies=[Depends(require_csrf)]
)


@router.post("", status_code=201, response_model=WorkspaceOut)
async def create_workspace(
    body: WorkspaceCreate, admin: AdminUser, session: UserSession
) -> WorkspaceOut:
    workspace = Workspace(id=uuid.uuid4(), name=body.name, slug=body.slug)
    session.add(workspace)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("A workspace with this slug already exists") from exc
    await record_audit(
        session,
        action="workspace.created",
        actor_id=admin.id,
        workspace_id=workspace.id,
        target=workspace.slug,
    )
    await session.commit()
    return WorkspaceOut(id=workspace.id, name=workspace.name, slug=workspace.slug, role="admin")


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(user: CurrentUser, session: UserSession) -> list[WorkspaceOut]:
    rows = await repository.list_workspaces(session, user_id=user.id, is_admin=user.is_admin)
    return [
        WorkspaceOut(id=workspace.id, name=workspace.name, slug=workspace.slug, role=role)
        for workspace, role in rows
    ]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(ctx: ViewerCtx) -> WorkspaceOut:
    workspace = await repository.get_workspace(ctx.session, ctx.workspace_id)
    if workspace is None:
        raise NotFoundError("Workspace not found")
    return WorkspaceOut(id=workspace.id, name=workspace.name, slug=workspace.slug, role=ctx.role)
