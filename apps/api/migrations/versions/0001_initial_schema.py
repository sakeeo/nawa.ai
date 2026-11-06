"""initial schema: identity, workspaces, audit, instance settings

Revision ID: 0001
Revises:
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _pk() -> sa.Column[sa.Uuid]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _ensure_app_role() -> str:
    role = os.environ["POSTGRES_APP_USER"]
    if not ROLE_PATTERN.fullmatch(role):
        raise RuntimeError("POSTGRES_APP_USER must match ^[a-z_][a-z0-9_]{0,62}$")
    password = os.environ["POSTGRES_APP_PASSWORD"].replace("'", "''")
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
    ).scalar()
    verb = "ALTER" if exists else "CREATE"
    bind.exec_driver_sql(
        f"{verb} ROLE {role} LOGIN PASSWORD '{password}'"
        " NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
    )
    return role


def upgrade() -> None:
    op.create_table(
        "users",
        _pk(),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
    )
    op.create_table(
        "workspaces",
        _pk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        _created_at(),
    )
    op.create_table(
        "memberships",
        _pk(),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.Text(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("workspace_id", "user_id"),
        sa.CheckConstraint("role IN ('manager', 'member', 'viewer')", name="ck_memberships_role"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "invites",
        _pk(),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created_at(),
        sa.CheckConstraint("role IN ('manager', 'member', 'viewer')", name="ck_invites_role"),
    )
    op.create_index("ix_invites_workspace_id", "invites", ["workspace_id"])
    op.create_table(
        "refresh_tokens",
        _pk(),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by", sa.Uuid()),
        _created_at(),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_table(
        "audit_logs",
        _pk(),
        sa.Column("workspace_id", sa.Uuid()),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target", sa.Text()),
        _created_at(),
    )
    op.create_index("ix_audit_logs_workspace_created", "audit_logs", ["workspace_id", "created_at"])
    op.create_table(
        "instance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("setup_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("setup_token_hash", sa.Text()),
        sa.Column("ai_provider", sa.Text()),
        sa.Column(
            "demo_data_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint("id = 1", name="ck_instance_settings_singleton"),
    )
    op.execute("INSERT INTO instance_settings (id) VALUES (1)")

    role = _ensure_app_role()
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON users, workspaces, memberships, invites,"
        f" refresh_tokens, instance_settings TO {role}"
    )
    # Append-only: the app can never edit or delete audit history.
    op.execute(f"GRANT SELECT, INSERT ON audit_logs TO {role}")


def downgrade() -> None:
    # The application role is cluster-wide and may serve other databases; it is not dropped.
    for table in (
        "instance_settings",
        "audit_logs",
        "refresh_tokens",
        "invites",
        "memberships",
        "workspaces",
        "users",
    ):
        op.drop_table(table)
