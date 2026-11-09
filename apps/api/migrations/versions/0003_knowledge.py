"""knowledge: documents, chunks (pgvector + full-text), chat history, evaluation runs

Revision ID: 0003
Revises: 0002
"""

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Tables that carry workspace_id directly. eval_results hangs off eval_runs.
TENANT_TABLES = (
    "knowledge_bases",
    "documents",
    "chunks",
    "conversations",
    "messages",
    "citations",
    "feedback",
    "eval_runs",
)
ALL_TABLES = (*TENANT_TABLES, "eval_results")

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


def _app_role() -> str:
    role = os.environ["POSTGRES_APP_USER"]
    if not ROLE_PATTERN.fullmatch(role):
        raise RuntimeError("POSTGRES_APP_USER must match ^[a-z_][a-z0-9_]{0,62}$")
    return role


def upgrade() -> None:
    role = _app_role()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_bases",
        _pk(),
        _ws(),
        sa.Column("name", sa.Text(), nullable=False),
        _ts("created_at"),
    )
    op.create_table(
        "documents",
        _pk(),
        _ws(),
        sa.Column(
            "knowledge_base_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts("created_at"),
        sa.UniqueConstraint("knowledge_base_id", "sha256", name="uq_documents_kb_sha256"),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'ready', 'failed')", name="ck_documents_status"
        ),
    )
    op.create_index("documents_workspace_idx", "documents", ["workspace_id", "knowledge_base_id"])

    op.execute(
        "CREATE TABLE chunks ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,"
        " document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
        " ordinal integer NOT NULL,"
        " text text NOT NULL,"
        " page integer,"
        " section_path text,"
        " heading text,"
        " token_count integer NOT NULL,"
        " embedding vector(1024),"
        " tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED)"
    )
    op.create_index("chunks_workspace_document_idx", "chunks", ["workspace_id", "document_id"])
    op.execute(
        "CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv)")

    op.create_table(
        "conversations",
        _pk(),
        _ws(),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("conversations_owner_idx", "conversations", ["workspace_id", "user_id"])
    op.create_table(
        "messages",
        _pk(),
        _ws(),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("refused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model", sa.Text()),
        sa.Column("prompt_name", sa.Text()),
        sa.Column("prompt_version", sa.Integer()),
        sa.Column("tokens_in", sa.Integer()),
        sa.Column("tokens_out", sa.Integer()),
        _ts("created_at"),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )
    op.create_index("messages_conversation_idx", "messages", ["conversation_id", "created_at"])
    op.create_table(
        "citations",
        _pk(),
        _ws(),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("marker", sa.Integer(), nullable=False),
    )
    op.create_index("citations_message_idx", "citations", ["message_id"])
    op.create_table(
        "feedback",
        _pk(),
        _ws(),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text()),
        _ts("created_at"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_feedback_value"),
    )
    op.create_table(
        "eval_runs",
        _pk(),
        _ws(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        _ts("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "eval_results",
        _pk(),
        sa.Column(
            "eval_run_id",
            sa.Uuid(),
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_id", sa.Text(), nullable=False),
        sa.Column("retrieved", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("answer", sa.Text()),
        sa.Column("metrics", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("eval_results_run_idx", "eval_results", ["eval_run_id"])

    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for table in TENANT_TABLES:
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} FOR ALL"
            f" USING ({TENANT_CLAUSE}) WITH CHECK ({TENANT_CLAUSE})"
        )
    # eval_results has no workspace_id; the eval_runs policy filters the subquery under RLS.
    op.execute(
        "CREATE POLICY eval_results_tenant ON eval_results FOR ALL"
        " USING (eval_run_id IN (SELECT id FROM eval_runs))"
        " WITH CHECK (eval_run_id IN (SELECT id FROM eval_runs))"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(ALL_TABLES)} TO {role}")


def downgrade() -> None:
    for table in reversed(ALL_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
