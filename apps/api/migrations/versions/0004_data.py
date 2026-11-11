"""data: data sources, schema snapshots, semantic models, query logs

Revision ID: 0004
Revises: 0003
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

TABLES = ("data_sources", "schema_snapshots", "semantic_models", "query_logs")

TENANT_CLAUSE = "workspace_id = app_workspace_id() OR app_is_admin()"


def _pk() -> sa.Column[sa.Uuid]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ws() -> sa.Column[sa.Uuid]:
    return sa.Column(
        "workspace_id",
        sa.Uuid(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )


def _ts(name: str) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _source_fk(*, nullable: bool, ondelete: str) -> sa.Column[sa.Uuid]:
    return sa.Column(
        "data_source_id",
        sa.Uuid(),
        sa.ForeignKey("data_sources.id", ondelete=ondelete),
        nullable=nullable,
    )


def _app_role() -> str:
    role = os.environ["POSTGRES_APP_USER"]
    if not ROLE_PATTERN.fullmatch(role):
        raise RuntimeError("POSTGRES_APP_USER must match ^[a-z_][a-z0-9_]{0,62}$")
    return role


def upgrade() -> None:
    role = _app_role()

    op.create_table(
        "data_sources",
        _pk(),
        _ws(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="postgres"),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("ssl_mode", sa.Text(), nullable=False, server_default="prefer"),
        sa.Column("status", sa.Text(), nullable=False, server_default="untested"),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_data_sources_workspace_name"),
        sa.CheckConstraint("kind = 'postgres'", name="ck_data_sources_kind"),
        sa.CheckConstraint("status IN ('untested', 'ok', 'failed')", name="ck_data_sources_status"),
    )

    op.create_table(
        "schema_snapshots",
        _pk(),
        _ws(),
        _source_fk(nullable=False, ondelete="CASCADE"),
        sa.Column("snapshot", JSONB(), nullable=False),
        _ts("created_at"),
    )
    op.execute(
        "CREATE INDEX schema_snapshots_source_idx ON schema_snapshots"
        " (data_source_id, created_at DESC)"
    )

    op.create_table(
        "semantic_models",
        _pk(),
        _ws(),
        _source_fk(nullable=False, ondelete="CASCADE"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("yaml", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts("created_at"),
        sa.UniqueConstraint("data_source_id", "version", name="uq_semantic_models_source_version"),
    )
    op.execute(
        "CREATE UNIQUE INDEX semantic_models_one_active ON semantic_models (data_source_id)"
        " WHERE is_active"
    )

    op.create_table(
        "query_logs",
        _pk(),
        _ws(),
        _source_fk(nullable=True, ondelete="SET NULL"),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("blocked_reason", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("row_count", sa.Integer()),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insight", sa.Text()),
        sa.Column("insight_grounded", sa.Boolean()),
        sa.Column("feedback", sa.SmallInteger()),
        _ts("created_at"),
        sa.CheckConstraint(
            "status IN ('ok', 'blocked', 'error', 'clarification')", name="ck_query_logs_status"
        ),
        sa.CheckConstraint("feedback IN (-1, 1)", name="ck_query_logs_feedback"),
    )
    op.execute(
        "CREATE INDEX query_logs_workspace_idx ON query_logs (workspace_id, created_at DESC)"
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} FOR ALL"
            f" USING ({TENANT_CLAUSE}) WITH CHECK ({TENANT_CLAUSE})"
        )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO {role}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
