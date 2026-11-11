from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import asyncpg
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

CONNECT_TIMEOUT_S = 5
MAX_REPORTED_TABLES = 5
SYSTEM_SCHEMAS = ("information_schema",)


@dataclass(frozen=True)
class ConnectionParams:
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)
    ssl_mode: str = "prefer"


def build_url(params: ConnectionParams) -> URL:
    """Build the URL from parts so the password is never formatted into a string."""
    return URL.create(
        "postgresql+asyncpg",
        username=params.username,
        password=params.password,
        host=params.host,
        port=params.port,
        database=params.database,
    )


def scrub(message: str, password: str) -> str:
    """Remove the password from text that may be logged or shown to a user."""
    return message.replace(password, "***") if password else message


@asynccontextmanager
async def open_engine(params: ConnectionParams) -> AsyncIterator[AsyncEngine]:
    """A short-lived engine without a pool. The caller never keeps it across requests."""
    engine = create_async_engine(
        build_url(params),
        poolclass=NullPool,
        connect_args={"timeout": CONNECT_TIMEOUT_S, "ssl": params.ssl_mode},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def connect_raw(params: ConnectionParams) -> asyncpg.Connection:
    """A single asyncpg connection for the executor. The caller must close it."""
    return await asyncpg.connect(
        host=params.host,
        port=params.port,
        user=params.username,
        password=params.password,
        database=params.database,
        ssl=params.ssl_mode,
        timeout=CONNECT_TIMEOUT_S,
        server_settings={"application_name": "nawa-data"},
    )


@dataclass(frozen=True)
class ConnectionReport:
    ok: bool
    server_version: str | None
    problems: list[str]


async def test_connection(
    params: ConnectionParams, *, tables: list[str] | None = None
) -> ConnectionReport:
    """Connect and verify the role is read-only (decision P3).

    Fails when the role is a superuser, can create objects in a user schema, or can write to any
    of `tables` (every user table when `None`). Messages never contain the password.
    """
    problems: list[str] = []
    version: str | None = None
    try:
        async with open_engine(params) as engine, engine.connect() as conn:
            version = (await conn.execute(text("SELECT version()"))).scalar_one()
            is_super = (
                await conn.execute(
                    text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                )
            ).scalar_one()
            if is_super:
                problems.append("The role is a superuser; use a read-only role.")
            schemas = (
                await conn.execute(
                    text(
                        "SELECT nspname FROM pg_namespace"
                        " WHERE nspname !~ '^pg_' AND nspname <> ALL(:system)"
                        " AND has_schema_privilege(current_user, oid, 'CREATE') ORDER BY nspname"
                    ),
                    {"system": list(SYSTEM_SCHEMAS)},
                )
            ).scalars()
            for schema in schemas:
                problems.append(f"The role can create objects in schema '{schema}'.")
            writable = (
                await conn.execute(
                    text(
                        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid ="
                        " c.relnamespace WHERE c.relkind IN ('r', 'p')"
                        " AND n.nspname !~ '^pg_' AND n.nspname <> ALL(:system)"
                        " AND (CAST(:tables AS text[]) IS NULL OR c.relname = ANY(:tables))"
                        " AND (has_table_privilege(current_user, c.oid, 'INSERT')"
                        " OR has_table_privilege(current_user, c.oid, 'UPDATE')"
                        " OR has_table_privilege(current_user, c.oid, 'DELETE')"
                        " OR has_table_privilege(current_user, c.oid, 'TRUNCATE'))"
                        " ORDER BY c.relname"
                    ),
                    {"system": list(SYSTEM_SCHEMAS), "tables": tables},
                )
            ).scalars()
            names = list(writable)
            if names:
                shown = ", ".join(names[:MAX_REPORTED_TABLES])
                more = len(names) - MAX_REPORTED_TABLES
                suffix = f" and {more} more" if more > 0 else ""
                problems.append(f"The role has write privileges on: {shown}{suffix}.")
    except Exception as exc:
        detail = scrub(f"{type(exc).__name__}: {exc}", params.password)[:200]
        return ConnectionReport(
            ok=False, server_version=None, problems=[f"Cannot connect: {detail}"]
        )
    return ConnectionReport(ok=not problems, server_version=version, problems=problems)
