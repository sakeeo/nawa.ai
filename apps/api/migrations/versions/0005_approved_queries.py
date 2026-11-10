"""data: approved queries used as few-shot examples

Revision ID: 0005
Revises: 0004
"""

import os
import re
from collections.abc import Sequence

from alembic import op

revision = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
TENANT_CLAUSE = "workspace_id = app_workspace_id() OR app_is_admin()"


def _app_role() -> str:
    role = os.environ["POSTGRES_APP_USER"]
    if not ROLE_PATTERN.fullmatch(role):
        raise RuntimeError("POSTGRES_APP_USER must match ^[a-z_][a-z0-9_]{0,62}$")
    return role


def upgrade() -> None:
    role = _app_role()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "CREATE TABLE approved_queries ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,"
        " data_source_id uuid NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,"
        " question text NOT NULL,"
        " sql text NOT NULL,"
        " embedding vector(1024) NOT NULL,"
        " approved_by uuid REFERENCES users(id) ON DELETE SET NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_approved_queries_source_question UNIQUE (data_source_id, question))"
    )
    op.create_index(
        "approved_queries_workspace_idx", "approved_queries", ["workspace_id", "data_source_id"]
    )
    op.execute(
        "CREATE INDEX approved_queries_embedding_hnsw ON approved_queries"
        " USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("ALTER TABLE approved_queries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approved_queries FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY approved_queries_tenant ON approved_queries FOR ALL"
        f" USING ({TENANT_CLAUSE}) WITH CHECK ({TENANT_CLAUSE})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON approved_queries TO {role}")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS approved_queries CASCADE")
