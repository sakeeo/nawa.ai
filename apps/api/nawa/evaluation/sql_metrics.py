"""Pure metrics for the Text-to-SQL evaluation: result comparison, rates and failure categories."""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from nawa.data.executor import QueryResult
from nawa.evaluation.metrics import percentile

DIFFICULTIES = ("easy", "medium", "hard")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00$")


@dataclass(frozen=True)
class SqlItemResult:
    """What the runner records per answerable item; every rate below reads only these fields."""

    id: str
    difficulty: str
    question: str
    status: str  # ok | blocked | error | clarification
    sql: str | None
    attempts: int
    correct: bool | None
    latency_ms: float
    error: str | None = None
    insight_grounded: bool | None = None
    tags: tuple[str, ...] = ()


# ---------------------------------------------------------------- comparing results


def _cell_key(value: Any) -> str:
    """A sortable text for one cell. Numbers compare to 2 decimals, so 1000, 1000.0 and
    '1000.00' agree; midnight timestamps equal plain dates; everything else is exact."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"b:{value}"
    if isinstance(value, int | float):
        return f"n:{round(float(value), 2):.2f}"
    if isinstance(value, str):
        if _NUMBER.match(value):
            return f"n:{round(float(value), 2):.2f}"
        midnight = _MIDNIGHT.match(value)
        return f"s:{midnight.group(1) if midnight else value}"
    return f"s:{value}"


def _row_signature(row: list[Any]) -> tuple[str, ...]:
    return tuple(sorted(_cell_key(cell) for cell in row))


def results_equal(actual: QueryResult, expected: QueryResult, *, ordered: bool) -> bool:
    """Same rows, ignoring column names and column order. Row order counts only if `ordered`."""
    got = [_row_signature(row) for row in actual.rows]
    want = [_row_signature(row) for row in expected.rows]
    if len(got) != len(want):
        return False
    return got == want if ordered else Counter(got) == Counter(want)


# ---------------------------------------------------------------- rates


def execution_accuracy(results: list[SqlItemResult], difficulty: str | None = None) -> float:
    pool = [r for r in results if difficulty is None or r.difficulty == difficulty]
    return sum(1 for r in pool if r.correct) / len(pool) if pool else 0.0


def valid_sql_rate(results: list[SqlItemResult], difficulty: str | None = None) -> float:
    """Share of items whose final SQL passed the guard and ran."""
    pool = [r for r in results if difficulty is None or r.difficulty == difficulty]
    return sum(1 for r in pool if r.status == "ok") / len(pool) if pool else 0.0


def self_correction_recovery_rate(results: list[SqlItemResult]) -> float | None:
    """Of the items whose first attempt failed, the share that ended with a valid result."""
    failed_first = [r for r in results if r.attempts > 1 or r.status == "error"]
    if not failed_first:
        return None
    return sum(1 for r in failed_first if r.status == "ok") / len(failed_first)


def dangerous_blocked_rate(blocked: Iterable[bool]) -> float:
    flags = list(blocked)
    return sum(1 for b in flags if b) / len(flags) if flags else 0.0


def insight_groundedness(results: list[SqlItemResult]) -> float | None:
    judged = [r.insight_grounded for r in results if r.insight_grounded is not None]
    return sum(1 for g in judged if g) / len(judged) if judged else None


def latency_summary(values: Iterable[float]) -> dict[str, float]:
    items = list(values)
    return {"p50": percentile(items, 50), "p95": percentile(items, 95)}


def summarize(
    results: list[SqlItemResult], *, dangerous: list[bool], insight_ms: list[float]
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "execution_accuracy": execution_accuracy(results),
        "valid_sql_rate": valid_sql_rate(results),
        "self_correction_recovery_rate": self_correction_recovery_rate(results),
        "dangerous_blocked_rate": dangerous_blocked_rate(dangerous),
        "insight_groundedness": insight_groundedness(results),
    }
    latency = latency_summary(r.latency_ms for r in results)
    metrics["p50_latency_ms"], metrics["p95_latency_ms"] = latency["p50"], latency["p95"]
    metrics["p50_insight_ms"] = percentile(insight_ms, 50)
    by_difficulty = {
        d: {
            "count": sum(1 for r in results if r.difficulty == d),
            "execution_accuracy": execution_accuracy(results, d),
            "valid_sql_rate": valid_sql_rate(results, d),
        }
        for d in DIFFICULTIES
        if any(r.difficulty == d for r in results)
    }
    counts = {
        "answerable": len(results),
        "dangerous": len(dangerous),
        "errors": sum(1 for r in results if r.status == "error"),
    }
    return {"metrics": metrics, "by_difficulty": by_difficulty, "counts": counts}


# ---------------------------------------------------------------- failure analysis


def categorize_failure(
    result: SqlItemResult, actual: QueryResult | None, expected: QueryResult | None
) -> str:
    """A coarse label for why an item failed, for the failure analysis. Heuristic by design."""
    if result.status == "blocked":
        return "guard false positive"
    if result.status == "clarification":
        return "no answer (clarification)"
    if result.status == "error":
        return "timeout" if "exceeded" in (result.error or "") else "execution error"
    if actual is None or expected is None:
        return "wrong aggregation"
    if len(actual.columns) != len(expected.columns):
        return "wrong column"
    if actual.row_count != expected.row_count:
        if "period" in result.tags or "relative_time" in result.tags:
            return "wrong period"
        return "wrong join" if "join" in result.tags else "wrong filter"
    return "wrong aggregation"
