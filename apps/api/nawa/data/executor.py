"""Safe execution of guarded SQL (layers 4 and 5): read-only transaction, timeout, row cap."""

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from math import isfinite
from typing import Any
from uuid import UUID

import asyncpg

from nawa.core.errors import DomainError
from nawa.data.connector import ConnectionParams, connect_raw, scrub
from nawa.data.guard import GuardedSql

JsonValue = str | int | float | bool | None | list[Any] | dict[str, Any]

MAX_MESSAGE_CHARS = 300
LOCK_TIMEOUT_MS = 2000
EXACT_FLOAT_DIGITS = 15


class QueryTimeoutError(DomainError):
    status_code = 504
    code = "query_timeout"
    title = "Query Timeout"


class QueryExecutionError(DomainError):
    status_code = 422
    code = "query_error"
    title = "Query Failed"


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[JsonValue]]
    row_count: int
    truncated: bool
    duration_ms: int


def _decimal(value: Decimal) -> JsonValue:
    if not value.is_finite():
        return str(value)
    if value == value.to_integral_value() and abs(value) < 2**53:
        return int(value)
    as_float = float(value)
    digits = len(value.as_tuple().digits)
    if digits <= EXACT_FLOAT_DIGITS and Decimal(repr(as_float)) == value:
        return as_float
    return str(value)


def to_json_value(value: Any) -> JsonValue:
    """Make a database value safe for strict JSON without losing precision silently."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, datetime | date | dtime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    return str(value)


def unique_names(names: list[str]) -> list[str]:
    """Suffix repeated column names (`total`, `total_2`, ...) so rows can be keyed by name."""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        candidate, counter = name, 1
        while candidate in seen:
            counter += 1
            candidate = f"{name}_{counter}"
        seen.add(candidate)
        result.append(candidate)
    return result


def _message(exc: BaseException, password: str) -> str:
    return scrub(str(exc).splitlines()[0] if str(exc) else type(exc).__name__, password)[
        :MAX_MESSAGE_CHARS
    ]


async def execute_readonly(
    params: ConnectionParams, sql: GuardedSql, *, timeout_s: int, max_rows: int
) -> QueryResult:
    """Run guarded SQL in a read-only transaction. Opens and closes its own connection.

    The statement timeout is enforced by the server; an outer client timeout covers a stalled
    network. Raises `QueryTimeoutError` or `QueryExecutionError`, never a driver exception.
    """
    started = time.perf_counter()
    conn: asyncpg.Connection | None = None
    try:
        async with asyncio.timeout(timeout_s + 3):
            conn = await connect_raw(params)
            async with conn.transaction(readonly=True):
                await conn.execute(
                    "SELECT set_config('statement_timeout', $1, true),"
                    " set_config('lock_timeout', $2, true)",
                    str(timeout_s * 1000),
                    str(LOCK_TIMEOUT_MS),
                )
                statement = await conn.prepare(sql)
                columns = unique_names([attribute.name for attribute in statement.get_attributes()])
                rows: list[list[JsonValue]] = []
                truncated = False
                async for record in statement.cursor():
                    if len(rows) >= max_rows:
                        truncated = True
                        break
                    rows.append([to_json_value(value) for value in record.values()])
    except asyncpg.QueryCanceledError as exc:
        raise QueryTimeoutError(f"The query exceeded {timeout_s} seconds") from exc
    except TimeoutError as exc:
        raise QueryTimeoutError(f"The query exceeded {timeout_s} seconds") from exc
    except asyncpg.PostgresError as exc:
        raise QueryExecutionError(_message(exc, params.password)) from exc
    except (OSError, asyncpg.InterfaceError) as exc:
        raise QueryExecutionError("The data source cannot be reached") from exc
    finally:
        if conn is not None:
            conn.terminate()
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
