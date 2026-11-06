import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Text, Uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from nawa.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    target: str | None = None,
) -> None:
    """Queue an audit row. The caller commits."""
    session.add(
        AuditLog(action=action, actor_id=actor_id, workspace_id=workspace_id, target=target)
    )
