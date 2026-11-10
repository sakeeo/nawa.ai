import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nawa.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _workspace_fk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), index=False)


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_data_sources_workspace_name"),
        CheckConstraint("kind = 'postgres'", name="ck_data_sources_kind"),
        CheckConstraint("status IN ('untested', 'ok', 'failed')", name="ck_data_sources_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="postgres")
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    database: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text)
    password_encrypted: Mapped[str] = mapped_column(Text)
    ssl_mode: Mapped[str] = mapped_column(Text, default="prefer")
    status: Mapped[str] = mapped_column(Text, default="untested")
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class SchemaSnapshot(Base):
    __tablename__ = "schema_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE")
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SemanticModel(Base):
    __tablename__ = "semantic_models"
    __table_args__ = (
        UniqueConstraint("data_source_id", "version", name="uq_semantic_models_source_version"),
        Index(
            "semantic_models_one_active",
            "data_source_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    yaml: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class QueryLog(Base):
    __tablename__ = "query_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'blocked', 'error', 'clarification')", name="ck_query_logs_status"
        ),
        CheckConstraint("feedback IN (-1, 1)", name="ck_query_logs_feedback"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL"), default=None
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(Text)
    blocked_reason: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    row_count: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    insight: Mapped[str | None] = mapped_column(Text, default=None)
    insight_grounded: Mapped[bool | None] = mapped_column(Boolean, default=None)
    feedback: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
