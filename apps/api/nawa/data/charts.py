"""Deterministic chart choice from the shape of a result (decision P8). No model call."""

import re
from dataclasses import dataclass
from typing import Any, Literal

ChartKind = Literal["kpi", "bar", "line", "table"]
ColumnKind = Literal["numeric", "temporal", "categorical", "empty"]

MAX_BAR_ROWS = 20
MAX_SERIES = 3
_ISO = re.compile(r"^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$")


@dataclass(frozen=True)
class ChartSpec:
    kind: ChartKind
    x: str | None
    y: list[str]
    title: str


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def column_kinds(columns: list[str], rows: list[list[Any]]) -> dict[str, ColumnKind]:
    """Kind of each column from its non-null values. All-null columns are `empty`."""
    kinds: dict[str, ColumnKind] = {}
    for index, name in enumerate(columns):
        values = [row[index] for row in rows if row[index] is not None]
        if not values:
            kinds[name] = "empty"
        elif all(_is_number(v) for v in values):
            kinds[name] = "numeric"
        elif all(isinstance(v, str) and _ISO.match(v) for v in values):
            kinds[name] = "temporal"
        else:
            kinds[name] = "categorical"
    return kinds


def _table() -> ChartSpec:
    return ChartSpec("table", None, [], "")


def choose_chart(columns: list[str], rows: list[list[Any]]) -> ChartSpec:
    if not rows:
        return _table()
    kinds = column_kinds(columns, rows)
    numeric = [c for c in columns if kinds[c] == "numeric"]
    temporal = [c for c in columns if kinds[c] == "temporal"]
    categorical = [c for c in columns if kinds[c] == "categorical"]
    if not numeric:
        return _table()

    if len(rows) == 1:
        if len(numeric) == 1 and len(columns) <= 2:
            return ChartSpec("kpi", None, numeric, numeric[0])
        return _table()

    if len(numeric) > MAX_SERIES or categorical and temporal:
        return _table()
    if len(temporal) == 1 and not categorical:
        return ChartSpec("line", temporal[0], numeric, f"{', '.join(numeric)} per {temporal[0]}")
    if len(categorical) == 1 and not temporal and len(rows) <= MAX_BAR_ROWS:
        return ChartSpec(
            "bar", categorical[0], numeric, f"{', '.join(numeric)} per {categorical[0]}"
        )
    return _table()
