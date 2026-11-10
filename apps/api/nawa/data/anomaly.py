"""Simple anomaly notes for time series: points far from the series mean (z-score)."""

import math
from dataclasses import dataclass
from typing import Any, Literal

from nawa.data.charts import column_kinds

DEFAULT_THRESHOLD = 2.0
DEFAULT_MIN_POINTS = 6


@dataclass(frozen=True)
class Anomaly:
    label: str
    value: float
    z: float
    direction: Literal["high", "low"]


def zscore_anomalies(
    series: list[tuple[str, float]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_points: int = DEFAULT_MIN_POINTS,
) -> list[Anomaly]:
    """Points whose |z| reaches `threshold`, strongest first (ties by label).

    Uses the population standard deviation. Nothing is reported for fewer than `min_points`
    points or for a series with no variation. The numbers are computed here, not by a model.
    """
    if len(series) < min_points:
        return []
    values = [value for _, value in series]
    mean = sum(values) / len(values)
    deviation = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    if deviation == 0:
        return []
    found = [
        Anomaly(
            label, value, round((value - mean) / deviation, 2), "high" if value > mean else "low"
        )
        for label, value in series
        if abs((value - mean) / deviation) >= threshold
    ]
    return sorted(found, key=lambda a: (-abs(a.z), a.label))


def detect_anomalies(
    columns: list[str], rows: list[list[Any]], *, threshold: float = DEFAULT_THRESHOLD
) -> list[Anomaly]:
    """Anomalies of the first numeric column over the one temporal column of a result.

    Only a result with exactly one temporal column, no label columns and at least one number is
    treated as a time series; anything else gives no anomalies.
    """
    kinds = column_kinds(columns, rows)
    temporal = [c for c in columns if kinds[c] == "temporal"]
    numeric = [c for c in columns if kinds[c] == "numeric"]
    if len(temporal) != 1 or not numeric or any(kinds[c] == "categorical" for c in columns):
        return []
    at, value_at = columns.index(temporal[0]), columns.index(numeric[0])
    series = sorted(
        (str(row[at])[:10], float(row[value_at])) for row in rows if row[value_at] is not None
    )
    return zscore_anomalies(series, threshold=threshold)
