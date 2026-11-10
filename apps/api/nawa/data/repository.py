import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.crypto import CredentialVault
from nawa.data.connector import ConnectionParams
from nawa.data.discovery import TableInfo, snapshot_from_json, snapshot_to_json
from nawa.data.models import DataSource, QueryLog, SchemaSnapshot


async def create_source(
    session: AsyncSession,
    vault: CredentialVault,
    *,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID | None,
    name: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    ssl_mode: str,
) -> DataSource:
    """Store a source. The password is encrypted before it reaches the session."""
    source = DataSource(
        workspace_id=workspace_id,
        created_by=created_by,
        name=name,
        host=host,
        port=port,
        database=database,
        username=username,
        password_encrypted=vault.encrypt(password),
        ssl_mode=ssl_mode,
    )
    session.add(source)
    await session.flush()
    return source


async def get_source(
    session: AsyncSession, workspace_id: uuid.UUID, source_id: uuid.UUID
) -> DataSource | None:
    result = await session.execute(
        select(DataSource).where(
            DataSource.id == source_id, DataSource.workspace_id == workspace_id
        )
    )
    return result.scalar_one_or_none()


async def list_sources(session: AsyncSession, workspace_id: uuid.UUID) -> list[DataSource]:
    result = await session.execute(
        select(DataSource)
        .where(DataSource.workspace_id == workspace_id)
        .order_by(DataSource.created_at, DataSource.id)
    )
    return list(result.scalars())


async def delete_source(
    session: AsyncSession, workspace_id: uuid.UUID, source_id: uuid.UUID
) -> bool:
    result = await session.execute(
        delete(DataSource)
        .where(DataSource.id == source_id, DataSource.workspace_id == workspace_id)
        .returning(DataSource.id)
    )
    return result.first() is not None


async def set_source_status(
    session: AsyncSession, source: DataSource, *, ok: bool, error: str | None
) -> None:
    source.status = "ok" if ok else "failed"
    source.last_error = None if ok else error
    await session.flush()


def params_for(source: DataSource, vault: CredentialVault) -> ConnectionParams:
    """Decrypt the stored password for one connection. Keep the result out of logs."""
    return ConnectionParams(
        host=source.host,
        port=source.port,
        database=source.database,
        username=source.username,
        password=vault.decrypt(source.password_encrypted),
        ssl_mode=source.ssl_mode,
    )


async def save_snapshot(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    tables: list[TableInfo],
) -> SchemaSnapshot:
    snapshot = SchemaSnapshot(
        workspace_id=workspace_id, data_source_id=source_id, snapshot=snapshot_to_json(tables)
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def latest_snapshot(
    session: AsyncSession, workspace_id: uuid.UUID, source_id: uuid.UUID
) -> list[TableInfo] | None:
    result = await session.execute(
        select(SchemaSnapshot)
        .where(
            SchemaSnapshot.workspace_id == workspace_id,
            SchemaSnapshot.data_source_id == source_id,
        )
        .order_by(SchemaSnapshot.created_at.desc(), SchemaSnapshot.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return snapshot_from_json(row.snapshot) if row else None


async def log_query(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    data_source_id: uuid.UUID | None,
    question: str,
    sql: str | None,
    status: str,
    blocked_reason: str | None,
    attempts: int,
    row_count: int | None,
    duration_ms: int,
) -> uuid.UUID:
    """Record one terminal outcome, blocked ones included (decision P13).

    The caller must commit even when the request ends in an error response, or the audit row
    of a rejected query is lost with the rolled-back transaction.
    """
    entry = QueryLog(
        workspace_id=workspace_id,
        user_id=user_id,
        data_source_id=data_source_id,
        question=question,
        sql=sql,
        status=status,
        blocked_reason=blocked_reason,
        attempts=attempts,
        row_count=row_count,
        duration_ms=duration_ms,
    )
    session.add(entry)
    await session.flush()
    return entry.id


async def update_query_insight(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    query_id: uuid.UUID,
    *,
    insight: str,
    grounded: bool,
) -> bool:
    result = await session.execute(
        update(QueryLog)
        .where(QueryLog.id == query_id, QueryLog.workspace_id == workspace_id)
        .values(insight=insight, insight_grounded=grounded)
        .returning(QueryLog.id)
    )
    return result.first() is not None


async def list_queries(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[QueryLog]:
    """Newest first. Pass `user_id` for a member's own history; omit it for managers."""
    statement = select(QueryLog).where(QueryLog.workspace_id == workspace_id)
    if user_id is not None:
        statement = statement.where(QueryLog.user_id == user_id)
    result = await session.execute(
        statement.order_by(QueryLog.created_at.desc(), QueryLog.id.desc()).limit(limit)
    )
    return list(result.scalars())
