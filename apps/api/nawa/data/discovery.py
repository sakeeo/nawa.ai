from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

MAX_SAMPLE_VALUES = 20
MAX_SAMPLE_LENGTH = 40


@dataclass(frozen=True)
class ForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    samples: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    primary_key: list[str]
    foreign_keys: list[ForeignKey]
    row_estimate: int


_COLUMNS_SQL = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema AND c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

_CONSTRAINTS_SQL = """
SELECT c.relname, con.contype::text,
  ARRAY(SELECT a.attname::text FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
        ORDER BY k.ord),
  rc.relname,
  ARRAY(SELECT a.attname::text FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum
        ORDER BY k.ord)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_class rc ON rc.oid = con.confrelid
WHERE n.nspname = :schema AND con.contype IN ('p', 'f')
ORDER BY c.relname, con.conname
"""

_ESTIMATES_SQL = """
SELECT c.relname, GREATEST(c.reltuples, 0)::bigint
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')
"""


def _is_text_type(type_name: str) -> bool:
    return type_name.startswith(("text", "character", "citext"))


async def discover_schema(
    engine: AsyncEngine,
    *,
    schema: str = "public",
    exclude: set[tuple[str, str]] | frozenset[tuple[str, str]] = frozenset(),
    sample_allow: dict[str, set[str]] | None = None,
) -> list[TableInfo]:
    """Read tables, columns, keys and enum-like sample values (decision P12).

    `exclude` holds (table, column) pairs that must never be sampled (sensitive or omitted).
    `sample_allow`, when given, limits sampling to the listed columns of the listed tables: `{}`
    means no sampling at all. The table list itself is always complete.
    """
    params = {"schema": schema}
    async with engine.connect() as conn:
        column_rows = (await conn.execute(text(_COLUMNS_SQL), params)).all()
        constraint_rows = (await conn.execute(text(_CONSTRAINTS_SQL), params)).all()
        estimate_rows = (await conn.execute(text(_ESTIMATES_SQL), params)).all()
        quote = conn.dialect.identifier_preparer.quote

        samples: dict[tuple[str, str], list[str]] = {}
        for table, column, type_name, _nullable in column_rows:
            if (table, column) in exclude or not _is_text_type(type_name):
                continue
            if sample_allow is not None and column not in sample_allow.get(table, set()):
                continue
            col, tbl = quote(column), f"{quote(schema)}.{quote(table)}"
            # Identifiers are quoted by the dialect; the limit is a module constant.
            sample_sql = (
                f"SELECT DISTINCT {col}::text FROM {tbl} WHERE {col} IS NOT NULL"  # noqa: S608
                f" ORDER BY 1 LIMIT {MAX_SAMPLE_VALUES + 1}"
            )
            rows = (await conn.execute(text(sample_sql))).scalars().all()
            values = [str(v) for v in rows]
            if len(values) <= MAX_SAMPLE_VALUES and all(
                len(v) <= MAX_SAMPLE_LENGTH for v in values
            ):
                samples[(table, column)] = values

    primary_keys: dict[str, list[str]] = {}
    foreign_keys: dict[str, list[ForeignKey]] = {}
    for table, kind, columns, ref_table, ref_columns in constraint_rows:
        if kind == "p":
            primary_keys[table] = list(columns)
        else:
            foreign_keys.setdefault(table, []).append(
                ForeignKey(list(columns), ref_table, list(ref_columns))
            )
    estimates = {name: int(rows) for name, rows in estimate_rows}

    grouped: dict[str, list[ColumnInfo]] = {}
    for table, column, type_name, nullable in column_rows:
        grouped.setdefault(table, []).append(
            ColumnInfo(column, type_name, bool(nullable), samples.get((table, column), []))
        )
    return [
        TableInfo(
            name=name,
            columns=columns,
            primary_key=primary_keys.get(name, []),
            foreign_keys=foreign_keys.get(name, []),
            row_estimate=estimates.get(name, 0),
        )
        for name, columns in grouped.items()
    ]


def snapshot_to_json(tables: list[TableInfo]) -> dict[str, Any]:
    return {
        "tables": [
            {
                "name": t.name,
                "primary_key": t.primary_key,
                "row_estimate": t.row_estimate,
                "columns": [
                    {"name": c.name, "type": c.type, "nullable": c.nullable, "samples": c.samples}
                    for c in t.columns
                ],
                "foreign_keys": [
                    {"columns": f.columns, "ref_table": f.ref_table, "ref_columns": f.ref_columns}
                    for f in t.foreign_keys
                ],
            }
            for t in tables
        ]
    }


def snapshot_from_json(data: dict[str, Any]) -> list[TableInfo]:
    return [
        TableInfo(
            name=t["name"],
            columns=[
                ColumnInfo(c["name"], c["type"], c["nullable"], list(c["samples"]))
                for c in t["columns"]
            ],
            primary_key=list(t["primary_key"]),
            foreign_keys=[
                ForeignKey(list(f["columns"]), f["ref_table"], list(f["ref_columns"]))
                for f in t["foreign_keys"]
            ],
            row_estimate=int(t["row_estimate"]),
        )
        for t in data["tables"]
    ]
