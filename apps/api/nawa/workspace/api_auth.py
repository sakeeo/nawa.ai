from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.db import apply_rls
from nawa.core.ratelimit import RateLimiter, get_limiter
from nawa.workspace import auth_service, repository
from nawa.workspace.cookies import set_auth_cookies
from nawa.workspace.deps import CurrentUser, SessionDep, SettingsDep
from nawa.workspace.models import User
from nawa.workspace.schemas import LoginRequest, MembershipOut, MeOut, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

LimiterDep = Annotated[RateLimiter, Depends(get_limiter)]


async def build_me(session: AsyncSession, user: User) -> MeOut:
    # A commit ends the transaction-local RLS settings, so apply them again before reading.
    await apply_rls(session, user_id=user.id, is_admin=user.is_admin)
    memberships = await repository.list_memberships(session, user.id)
    return MeOut(
        user=UserOut.model_validate(user),
        memberships=[MembershipOut.model_validate(m) for m in memberships],
    )


@router.post("/login", response_model=MeOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    limiter: LimiterDep,
    settings: SettingsDep,
) -> MeOut:
    ip = request.client.host if request.client else "unknown"
    user, tokens = await auth_service.login(
        session, limiter, settings, email=body.email, password=body.password, ip=ip
    )
    set_auth_cookies(response, settings, tokens)
    return await build_me(session, user)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, session: SessionDep) -> MeOut:
    return await build_me(session, user)
