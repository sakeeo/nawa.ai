import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nawa.core.db import apply_rls
from nawa.data import repository
from nawa.data.connector import ConnectionParams, open_engine
from nawa.data.executor import (
    QueryExecutionError,
    QueryResult,
    QueryTimeoutError,
    execute_readonly,
)
from nawa.data.guard import GuardedSql, GuardResult, mark_checked
from tests.integration.conftest import TargetDb
from tests.integration.helpers import insert_user, insert_workspace


def _sql(statement: str) -> GuardedSql:
    """Bypass the guard on purpose: these tests prove the executor is safe on its own."""
    return GuardedSql(statement)


def _ro(target: TargetDb) -> ConnectionParams:
    assert isinstance(target.readonly, ConnectionParams)
    return target.readonly


def _owner(target: TargetDb) -> ConnectionParams:
    assert isinstance(target.owner, ConnectionParams)
    return target.owner


async def _run(target: TargetDb, statement: str, *, owner: bool = False, **kw: int) -> QueryResult:
    params = _owner(target) if owner else _ro(target)
    return await execute_readonly(
        params,
        _sql(statement),
        timeout_s=kw.get("timeout_s", 10),
        max_rows=kw.get("max_rows", 1000),
    )


async def _scalar(target: TargetDb, statement: str) -> object:
    async with open_engine(_owner(target)) as engine, engine.connect() as conn:
        return (await conn.execute(text(statement))).scalar_one()


async def test_returns_columns_rows_and_timing(target_database: TargetDb) -> None:
    result = await _run(target_database, "SELECT id, channel FROM orders ORDER BY id LIMIT 3")
    assert result.columns == ["id", "channel"]
    assert [row[0] for row in result.rows] == [1, 2, 3]
    assert result.row_count == 3 and result.truncated is False
    assert result.duration_ms >= 0


async def test_empty_result_still_reports_columns(target_database: TargetDb) -> None:
    result = await _run(target_database, "SELECT id, channel FROM orders WHERE false")
    assert result.columns == ["id", "channel"]
    assert result.rows == [] and result.row_count == 0 and result.truncated is False


async def test_colons_percent_signs_and_casts_reach_the_database_untouched(
    target_database: TargetDb,
) -> None:
    result = await _run(
        target_database,
        "SELECT 'a :b c' AS x, 'ab' LIKE '%b' AS y, '10:30'::time AS z, 100 % 7 AS m",
    )
    assert result.rows == [["a :b c", True, "10:30:00", 2]]


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO outlets VALUES (9, 'x', 'y')",
        "UPDATE outlets SET name = 'x'",
        "DELETE FROM orders",
        "CREATE TABLE evil (a int)",
        "DROP TABLE orders",
        "TRUNCATE orders",
        "WITH x AS (INSERT INTO outlets VALUES (9, 'x', 'y') RETURNING id) SELECT * FROM x",
    ],
)
async def test_writes_fail_inside_the_read_only_transaction_even_for_a_writable_role(
    target_database: TargetDb, statement: str
) -> None:
    with pytest.raises(QueryExecutionError):
        await _run(target_database, statement, owner=True)
    assert await _scalar(target_database, "SELECT count(*) FROM outlets") == 3
    assert await _scalar(target_database, "SELECT count(*) FROM orders") == 40


async def test_statement_timeout_raises_quickly_and_the_next_query_works(
    target_database: TargetDb,
) -> None:
    started = time.perf_counter()
    with pytest.raises(QueryTimeoutError):
        await _run(target_database, "SELECT pg_sleep(3)", timeout_s=1)
    assert time.perf_counter() - started < 2.5
    result = await _run(target_database, "SELECT 1 AS one")
    assert result.rows == [[1]]


async def test_more_rows_than_the_cap_are_truncated(target_database: TargetDb) -> None:
    result = await _run(
        target_database, "SELECT g FROM generate_series(1, 1005) g ORDER BY g", max_rows=1000
    )
    assert result.row_count == 1000 and len(result.rows) == 1000
    assert result.truncated is True
    assert result.rows[-1] == [1000]


async def test_exactly_the_cap_is_not_truncated(target_database: TargetDb) -> None:
    result = await _run(target_database, "SELECT g FROM generate_series(1, 50) g", max_rows=50)
    assert result.row_count == 50 and result.truncated is False


async def test_awkward_values_serialize_to_strict_json(target_database: TargetDb) -> None:
    result = await _run(
        target_database,
        "SELECT NULL AS n, 12.30::numeric(10,2) AS price, 12345678901234567890.123456::numeric AS"
        " huge, DATE '2025-08-01' AS d, TIMESTAMP '2025-08-01 10:30:00' AS ts, 'ab'::bytea AS b,"
        " 'f81d4fae-7dec-11d0-a765-00a0c91e6bf6'::uuid AS u, INTERVAL '2 days' AS iv,"
        " 'NaN'::float8 AS nan, '{\"a\": [1, 2]}'::jsonb AS j, ARRAY[1, 2] AS arr,"
        " 1 AS total, 2 AS total, 3 AS total, 'é' AS \"é\", true AS flag, 7 AS i",
    )
    assert result.columns == [
        "n", "price", "huge", "d", "ts", "b", "u", "iv", "nan", "j", "arr",
        "total", "total_2", "total_3", "é", "flag", "i",
    ]  # fmt: skip
    row = dict(zip(result.columns, result.rows[0], strict=True))
    assert row["n"] is None
    assert row["price"] == 12.3
    assert row["huge"] == "12345678901234567890.123456"
    assert row["d"] == "2025-08-01"
    assert row["ts"] == "2025-08-01T10:30:00"
    assert row["b"] == "6162"
    assert row["u"] == "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"
    assert row["nan"] is None or row["nan"] == "NaN"
    assert row["arr"] == [1, 2]
    assert row["flag"] is True and row["i"] == 7
    json.dumps(result.rows, allow_nan=False)


async def test_database_errors_are_wrapped_without_leaking_the_password(
    target_database: TargetDb,
) -> None:
    owner = _owner(target_database)
    with pytest.raises(QueryExecutionError) as info:
        await _run(target_database, "SELECT nope FROM orders", owner=True)
    assert owner.password not in str(info.value)
    assert len(str(info.value)) <= 300
    bad = ConnectionParams(
        owner.host, owner.port, owner.database, owner.username, "wrong-pw-1", "prefer"
    )
    with pytest.raises(QueryExecutionError) as info:
        await execute_readonly(bad, _sql("SELECT 1"), timeout_s=5, max_rows=10)
    assert "wrong-pw-1" not in str(info.value)


async def test_unreachable_server_is_an_execution_error(target_database: TargetDb) -> None:
    ro = _ro(target_database)
    nowhere = ConnectionParams("127.0.0.1", 1, ro.database, ro.username, "secret-x", "prefer")
    with pytest.raises(QueryExecutionError) as info:
        await execute_readonly(nowhere, _sql("SELECT 1"), timeout_s=2, max_rows=10)
    assert "secret-x" not in str(info.value)


def test_mark_checked_refuses_a_failed_guard_result() -> None:
    failed = GuardResult(ok=False, sql=None, kind="forbidden", reason="no", tables=frozenset())
    with pytest.raises(ValueError):
        mark_checked(failed)
    ok = GuardResult(ok=True, sql="SELECT 1 LIMIT 1", kind="ok", reason=None, tables=frozenset())
    assert mark_checked(ok) == "SELECT 1 LIMIT 1"


@asynccontextmanager
async def _scoped(engine: AsyncEngine, workspace_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await apply_rls(session, workspace_id=workspace_id)
        yield session


async def test_blocked_attempts_are_logged_and_isolated_per_workspace(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws_a = await insert_workspace(owner_engine, "alpha")
    ws_b = await insert_workspace(owner_engine, "beta")
    user_a = await insert_user(owner_engine, "a@example.com")
    user_b = await insert_user(owner_engine, "b@example.com")
    async with _scoped(app_engine, ws_a) as session:
        blocked_id = await repository.log_query(
            session,
            workspace_id=ws_a,
            user_id=user_a,
            data_source_id=None,
            question="hapus semua pesanan",
            sql=None,
            status="blocked",
            blocked_reason="Only a single read-only SELECT query is allowed",
            attempts=1,
            row_count=None,
            duration_ms=4,
        )
        await repository.log_query(
            session,
            workspace_id=ws_a,
            user_id=user_b,
            data_source_id=None,
            question="berapa omzet",
            sql="SELECT 1 LIMIT 1000",
            status="ok",
            blocked_reason=None,
            attempts=2,
            row_count=1,
            duration_ms=12,
        )
        await session.commit()
    async with _scoped(app_engine, ws_a) as session:
        everyone = await repository.list_queries(session, ws_a)
        assert {q.status for q in everyone} == {"blocked", "ok"}
        mine = await repository.list_queries(session, ws_a, user_id=user_a)
        assert [q.id for q in mine] == [blocked_id]
        assert mine[0].blocked_reason and mine[0].sql is None
        assert mine[0].attempts == 1 and mine[0].duration_ms == 4
    async with _scoped(app_engine, ws_b) as session:
        assert await repository.list_queries(session, ws_b) == []
        assert await repository.list_queries(session, ws_a) == []  # RLS hides the rows


async def test_insight_can_be_attached_to_a_logged_query(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ws = await insert_workspace(owner_engine, "alpha")
    user = await insert_user(owner_engine, "a@example.com")
    async with _scoped(app_engine, ws) as session:
        query_id = await repository.log_query(
            session,
            workspace_id=ws,
            user_id=user,
            data_source_id=None,
            question="q",
            sql="SELECT 1 LIMIT 1000",
            status="ok",
            blocked_reason=None,
            attempts=1,
            row_count=1,
            duration_ms=1,
        )
        await session.commit()
    async with _scoped(app_engine, ws) as session:
        assert await repository.update_query_insight(
            session, ws, query_id, insight="Satu baris.", grounded=True
        )
        assert not await repository.update_query_insight(
            session, ws, uuid.uuid4(), insight="x", grounded=False
        )
        await session.commit()
    async with _scoped(app_engine, ws) as session:
        (entry,) = await repository.list_queries(session, ws)
        assert (entry.insight, entry.insight_grounded) == ("Satu baris.", True)
