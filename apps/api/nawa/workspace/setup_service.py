import asyncio
import logging
import secrets
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.audit import record_audit
from nawa.core.config import Settings
from nawa.core.errors import ConflictError, PermissionDeniedError, ValidationFailedError
from nawa.core.security import hash_password, hash_token, new_token
from nawa.workspace import repository
from nawa.workspace.models import User
from nawa.workspace.schemas import SetupRequest

logger = logging.getLogger("nawa.setup")


def available_providers(settings: Settings) -> list[str]:
    """Providers already configured in .env. External ones respect OFFLINE_MODE."""
    providers = ["ollama"]
    if settings.deepseek_api_key and not settings.offline_mode:
        providers.append("deepseek")
    return providers


async def ensure_setup_token(maker: async_sessionmaker[AsyncSession]) -> str | None:
    """Create and log a one-time setup token while the instance is still unclaimed.

    The token is logged on purpose (spec §3.6): it proves the person finishing setup can read
    the server logs. Only its hash is stored, and it dies when setup completes. A new token
    replaces the old one on every start.
    """
    async with maker() as session:
        if not await repository.setup_required(session):
            return None
        token = new_token()
        await repository.set_setup_token_hash(session, hash_token(token))
        await session.commit()
    logger.warning("First-run setup token (valid until setup completes): %s", token)
    return token


async def complete_setup(session: AsyncSession, settings: Settings, body: SetupRequest) -> User:
    if not await repository.setup_required(session):
        raise ConflictError("Setup is already completed")
    stored = (await repository.get_instance_settings(session)).setup_token_hash
    if stored is None or not secrets.compare_digest(stored, hash_token(body.setup_token)):
        raise PermissionDeniedError("Invalid setup token")
    if body.provider not in available_providers(settings):
        raise ValidationFailedError("This AI provider is not configured on the server")
    claimed = await repository.claim_setup(
        session, provider=body.provider, demo_data_requested=body.load_demo_data
    )
    if not claimed:
        raise ConflictError("Setup is already completed")

    user = User(
        id=uuid.uuid4(),
        email=body.email.lower(),
        password_hash=await asyncio.to_thread(hash_password, body.password),
        is_admin=True,
        is_active=True,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("Setup is already completed") from exc
    await record_audit(session, action="setup.completed", actor_id=user.id)
    await session.commit()
    return user
