import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.audit import record_audit
from nawa.core.config import Settings
from nawa.core.errors import AuthenticationError, RateLimitedError
from nawa.core.ratelimit import RateLimiter
from nawa.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_token,
    new_token,
    verify_password,
)
from nawa.workspace import repository
from nawa.workspace.models import RefreshToken, User


@dataclass(frozen=True)
class IssuedTokens:
    access: str
    refresh: str
    csrf: str


def _issue(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    *,
    family_id: uuid.UUID,
    refresh_id: uuid.UUID | None = None,
) -> IssuedTokens:
    """Queue a new refresh token row and return the raw tokens. The caller commits."""
    refresh = new_token()
    session.add(
        RefreshToken(
            id=refresh_id or uuid.uuid4(),
            user_id=user_id,
            family_id=family_id,
            token_hash=hash_token(refresh),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds),
        )
    )
    access = create_access_token(
        user_id=user_id, secret=settings.jwt_secret, ttl_seconds=settings.access_token_ttl_seconds
    )
    return IssuedTokens(access=access, refresh=refresh, csrf=new_token())


async def login(
    session: AsyncSession,
    limiter: RateLimiter,
    settings: Settings,
    *,
    email: str,
    password: str,
    ip: str,
) -> tuple[User, IssuedTokens]:
    email = email.strip().lower()
    ip_key = f"login:ip:{ip}"
    email_key = f"login:email:{email}"
    if await limiter.is_blocked(ip_key, settings.login_limit_per_ip) or await limiter.is_blocked(
        email_key, settings.login_limit_per_email
    ):
        raise RateLimitedError("Too many login attempts. Try again later.")

    user = await repository.get_user_by_email(session, email)
    # Always verify against a hash so unknown emails cost the same time as wrong passwords.
    password_ok = await asyncio.to_thread(
        verify_password, user.password_hash if user else DUMMY_HASH, password
    )
    if user is None or not password_ok or not user.is_active:
        await limiter.hit(ip_key)
        await limiter.hit(email_key)
        await record_audit(session, action="auth.login_failed", target=email)
        await session.commit()
        raise AuthenticationError("Invalid email or password")

    await limiter.reset(email_key)
    tokens = _issue(session, settings, user.id, family_id=uuid.uuid4())
    await record_audit(session, action="auth.login", actor_id=user.id)
    await session.commit()
    return user, tokens
