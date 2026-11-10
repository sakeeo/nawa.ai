import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nawa.core.crypto import CredentialVault
from nawa.data.connector import ConnectionParams
from nawa.data.discovery import TableInfo, snapshot_from_json, snapshot_to_json
from nawa.data.models import DataSource, SchemaSnapshot


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
