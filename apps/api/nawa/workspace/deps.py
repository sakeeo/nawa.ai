import secrets
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.config import Settings, get_settings
from nawa.core.db import apply_rls, get_session
from nawa.core.errors import AuthenticationError, PermissionDeniedError
from nawa.core.security import decode_access_token
from nawa.workspace import repository
from nawa.workspace.cookies import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER
from nawa.workspace.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def require_csrf(request: Request) -> None:
    """Double-submit check: the csrf cookie must equal the X-CSRF-Token header."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise PermissionDeniedError("CSRF token missing or invalid")


async def get_current_user(request: Request, settings: SettingsDep, session: SessionDep) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise AuthenticationError("Not authenticated")
    user_id = decode_access_token(token, secret=settings.jwt_secret)
    user = await repository.get_user(session, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_user_session(user: CurrentUser, session: SessionDep) -> AsyncSession:
    """The request session scoped to the logged-in user (own memberships, own workspaces)."""
    await apply_rls(session, user_id=user.id, is_admin=user.is_admin)
    return session


UserSession = Annotated[AsyncSession, Depends(get_user_session)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise PermissionDeniedError("Administrator access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def get_system_session(session: SessionDep) -> AsyncSession:
    """Cross-tenant session. Only for unauthenticated flows that must look across tenants
    (invite preview and accept). Never use it for authenticated routes."""
    await apply_rls(session, is_admin=True)
    return session


SystemSession = Annotated[AsyncSession, Depends(get_system_session)]
