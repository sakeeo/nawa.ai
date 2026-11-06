"""row-level security for tenant-scoped tables

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("memberships", "invites", "audit_logs", "workspaces")

POLICIES = {
    "memberships_select": (
        "memberships",
        "FOR SELECT",
        "USING (workspace_id = app_workspace_id() OR user_id = app_user_id() OR app_is_admin())",
    ),
    "memberships_write": (
        "memberships",
        "FOR ALL",
        "USING (workspace_id = app_workspace_id() OR app_is_admin())"
        " WITH CHECK (workspace_id = app_workspace_id() OR app_is_admin())",
    ),
    "invites_all": (
        "invites",
        "FOR ALL",
        "USING (workspace_id = app_workspace_id() OR app_is_admin())"
        " WITH CHECK (workspace_id = app_workspace_id() OR app_is_admin())",
    ),
    "audit_logs_select": (
        "audit_logs",
        "FOR SELECT",
        "USING (workspace_id = app_workspace_id() OR app_is_admin())",
    ),
    "audit_logs_insert": (
        "audit_logs",
        "FOR INSERT",
        "WITH CHECK (workspace_id IS NULL OR workspace_id = app_workspace_id() OR app_is_admin())",
    ),
    "workspaces_select": (
        "workspaces",
        "FOR SELECT",
        "USING (id = app_workspace_id() OR app_is_admin() OR id IN"
        " (SELECT workspace_id FROM memberships WHERE user_id = app_user_id()))",
    ),
    "workspaces_admin_write": (
        "workspaces",
        "FOR ALL",
        "USING (app_is_admin()) WITH CHECK (app_is_admin())",
    ),
}


def upgrade() -> None:
    op.execute(
        "CREATE FUNCTION app_workspace_id() RETURNS uuid LANGUAGE sql STABLE AS"
        " $$ SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid $$"
    )
    op.execute(
        "CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS"
        " $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$"
    )
    op.execute(
        "CREATE FUNCTION app_is_admin() RETURNS boolean LANGUAGE sql STABLE AS"
        " $$ SELECT COALESCE(NULLIF(current_setting('app.is_admin', true), '')::boolean, false) $$"
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    for name, (table, command, clause) in POLICIES.items():
        op.execute(f"CREATE POLICY {name} ON {table} {command} {clause}")


def downgrade() -> None:
    for name, (table, _command, _clause) in POLICIES.items():
        op.execute(f"DROP POLICY {name} ON {table}")
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION app_is_admin()")
    op.execute("DROP FUNCTION app_user_id()")
    op.execute("DROP FUNCTION app_workspace_id()")
