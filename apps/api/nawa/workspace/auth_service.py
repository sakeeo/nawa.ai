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


async def refresh(
    session: AsyncSession, settings: Settings, *, raw_token: str | None
) -> tuple[User, IssuedTokens]:
    if not raw_token:
        raise AuthenticationError("Not authenticated")
    # FOR UPDATE serialises concurrent uses of the same token: the loser sees it revoked.
    token = await repository.get_refresh_token_by_hash(
        session, hash_token(raw_token), for_update=True
    )
    if token is None:
        raise AuthenticationError("Not authenticated")
    now = datetime.now(UTC)
    if token.revoked_at is not None:
        # A rotated token came back: assume theft and kill the whole chain.
        await repository.revoke_family(session, token.family_id, now)
        await record_audit(session, action="auth.refresh_reuse_detected", actor_id=token.user_id)
        await session.commit()
        raise AuthenticationError("Not authenticated")
    if token.expires_at <= now:
        raise AuthenticationError("Not authenticated")
    user = await repository.get_user(session, token.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Not authenticated")

    new_id = uuid.uuid4()
    tokens = _issue(session, settings, user.id, family_id=token.family_id, refresh_id=new_id)
    token.revoked_at = now
    token.replaced_by = new_id
    await session.commit()
    return user, tokens


async def logout(session: AsyncSession, *, raw_token: str | None) -> None:
    if not raw_token:
        return
    token = await repository.get_refresh_token_by_hash(session, hash_token(raw_token))
    if token is None:
        return
    await repository.revoke_family(session, token.family_id, datetime.now(UTC))
    await record_audit(session, action="auth.logout", actor_id=token.user_id)
    await session.commit()
