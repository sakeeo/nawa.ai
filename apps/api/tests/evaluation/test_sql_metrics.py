import pytest

from nawa.data.executor import QueryResult
from nawa.evaluation.sql_metrics import (
    SqlItemResult,
    categorize_failure,
    dangerous_blocked_rate,
    execution_accuracy,
    insight_groundedness,
    latency_summary,
    results_equal,
    self_correction_recovery_rate,
    summarize,
    valid_sql_rate,
)


def qr(columns: list[str], rows: list[list[object]]) -> QueryResult:
    return QueryResult(columns, rows, len(rows), False, 1)  # type: ignore[arg-type]


class TestResultsEqual:
    def test_row_order_is_ignored_unless_ordered(self) -> None:
        a = qr(["n", "v"], [["a", 1], ["b", 2]])
        b = qr(["n", "v"], [["b", 2], ["a", 1]])
        assert results_equal(a, b, ordered=False)
        assert not results_equal(a, b, ordered=True)
        assert results_equal(a, a, ordered=True)

    def test_column_order_and_names_are_ignored(self) -> None:
        a = qr(["name", "revenue"], [["Bandung", 10]])
        b = qr(["omzet", "outlet"], [[10, "Bandung"]])
        assert results_equal(a, b, ordered=False)

    def test_an_extra_or_missing_column_fails(self) -> None:
        a = qr(["a"], [[1]])
        assert not results_equal(a, qr(["a", "b"], [[1, 2]]), ordered=False)
        assert not results_equal(qr(["a", "b"], [[1, 2]]), a, ordered=False)

    def test_numbers_match_across_types_and_numeric_strings(self) -> None:
        assert results_equal(qr(["x"], [[1000]]), qr(["x"], [[1000.0]]), ordered=False)
        assert results_equal(
            qr(["x"], [["50958.333333333333"]]), qr(["x"], [[50958.33]]), ordered=False
        )
        assert results_equal(qr(["x"], [[0.1 + 0.2]]), qr(["x"], [[0.3]]), ordered=False)

    def test_numbers_differing_by_more_than_the_tolerance_fail(self) -> None:
        assert not results_equal(qr(["x"], [[100.0]]), qr(["x"], [[100.5]]), ordered=False)
        assert not results_equal(qr(["x"], [[1]]), qr(["x"], [[2]]), ordered=False)

    def test_dates_with_a_midnight_time_equal_plain_dates(self) -> None:
        a = qr(["m"], [["2025-08-01T00:00:00"]])
        assert results_equal(a, qr(["m"], [["2025-08-01"]]), ordered=False)
        assert not results_equal(a, qr(["m"], [["2025-09-01"]]), ordered=False)

    def test_null_matches_only_null(self) -> None:
        assert results_equal(qr(["x"], [[None]]), qr(["x"], [[None]]), ordered=False)
        assert not results_equal(qr(["x"], [[None]]), qr(["x"], [[0]]), ordered=False)

    def test_duplicates_and_empty_results_are_counted(self) -> None:
        assert not results_equal(qr(["x"], [[1], [1]]), qr(["x"], [[1]]), ordered=False)
        assert results_equal(qr(["x"], []), qr(["x"], []), ordered=False)
        assert not results_equal(qr(["x"], []), qr(["x"], [[1]]), ordered=False)

    def test_text_is_compared_exactly_but_not_confused_with_numbers(self) -> None:
        assert not results_equal(qr(["x"], [["Bandung"]]), qr(["x"], [["bandung"]]), ordered=False)
        assert not results_equal(qr(["x"], [["12abc"]]), qr(["x"], [[12]]), ordered=False)
        assert results_equal(qr(["x"], [[True]]), qr(["x"], [[True]]), ordered=False)


def item(
    item_id: str,
    difficulty: str = "easy",
    *,
    status: str = "ok",
    correct: bool | None = True,
    attempts: int = 1,
    grounded: bool | None = None,
    latency: float = 100.0,
    tags: tuple[str, ...] = (),
    error: str | None = None,
) -> SqlItemResult:
    return SqlItemResult(
        id=item_id,
        difficulty=difficulty,
        question="q",
        status=status,
        sql="SELECT 1",
        attempts=attempts,
        correct=correct,
        latency_ms=latency,
        error=error,
        insight_grounded=grounded,
        tags=tags,
    )


def test_execution_accuracy_counts_every_item_overall_and_per_difficulty() -> None:
    results = [
        item("E1", "easy", correct=True),
        item("E2", "easy", correct=False),
        item("M1", "medium", correct=True),
        item("H1", "hard", status="error", correct=False),
    ]
    assert execution_accuracy(results) == pytest.approx(0.5)
    assert execution_accuracy(results, "easy") == pytest.approx(0.5)
    assert execution_accuracy(results, "medium") == 1.0
    assert execution_accuracy(results, "hard") == 0.0
    assert execution_accuracy([]) == 0.0


def test_valid_sql_means_the_final_query_passed_the_guard_and_ran() -> None:
    results = [
        item("1", status="ok"),
        item("2", status="blocked", correct=False),
        item("3", status="error", correct=False),
        item("4", status="clarification", correct=False),
    ]
    assert valid_sql_rate(results) == pytest.approx(0.25)


def test_recovery_counts_only_items_whose_first_attempt_failed() -> None:
    results = [
        item("1", attempts=1),
        item("2", attempts=2, status="ok"),
        item("3", attempts=3, status="ok"),
        item("4", attempts=3, status="error", correct=False),
    ]
    assert self_correction_recovery_rate(results) == pytest.approx(2 / 3)
    assert self_correction_recovery_rate([item("1")]) is None


def test_dangerous_blocked_counts_outcomes_that_returned_no_data() -> None:
    blocked = [(True), (True), (False)]
    assert dangerous_blocked_rate(blocked) == pytest.approx(2 / 3)
    assert dangerous_blocked_rate([]) == 0.0


def test_insight_groundedness_ignores_items_without_an_insight() -> None:
    results = [item("1", grounded=True), item("2", grounded=False), item("3", grounded=None)]
    assert insight_groundedness(results) == pytest.approx(0.5)
    assert insight_groundedness([item("1")]) is None


def test_latency_summary_reports_p50_and_p95() -> None:
    summary = latency_summary([float(v) for v in range(1, 101)])
    assert summary == {"p50": 50.0, "p95": 95.0}
    assert latency_summary([]) == {"p50": 0.0, "p95": 0.0}


def test_summarize_builds_the_metric_dict_with_a_difficulty_breakdown() -> None:
    results = [
        item("E1", "easy", latency=100),
        item("E2", "easy", correct=False, attempts=2, latency=300),
        item("M1", "medium", status="error", correct=False, attempts=3, latency=900),
    ]
    summary = summarize(results, dangerous=[True, True], insight_ms=[50.0])
    metrics = summary["metrics"]
    assert metrics["execution_accuracy"] == pytest.approx(1 / 3)
    assert metrics["valid_sql_rate"] == pytest.approx(2 / 3)
    assert metrics["dangerous_blocked_rate"] == 1.0
    assert metrics["p95_latency_ms"] == 900.0 and metrics["p50_latency_ms"] == 300.0
    assert metrics["p50_insight_ms"] == 50.0
    assert summary["by_difficulty"]["easy"] == {
        "count": 2,
        "execution_accuracy": 0.5,
        "valid_sql_rate": 1.0,
    }
    assert summary["by_difficulty"]["medium"]["count"] == 1
    assert summary["counts"] == {"answerable": 3, "dangerous": 2, "errors": 1}


class TestCategorizeFailure:
    def test_statuses_without_an_answer(self) -> None:
        assert (
            categorize_failure(item("1", status="blocked", correct=False), None, None)
            == "guard false positive"
        )
        clarified = item("1", status="clarification", correct=False)
        assert categorize_failure(clarified, None, None) == "no answer (clarification)"
        timed_out = item("1", status="error", correct=False, error="The query exceeded 10 seconds")
        assert categorize_failure(timed_out, None, None) == "timeout"
        broken = item("1", status="error", correct=False, error="Cannot resolve columns")
        assert categorize_failure(broken, None, None) == "execution error"

    def test_wrong_answers_are_told_apart_by_shape_and_tags(self) -> None:
        expected = qr(["a", "b"], [[1, 2], [3, 4]])
        wrong_shape = qr(["a"], [[1], [3]])
        assert categorize_failure(item("1", correct=False), wrong_shape, expected) == "wrong column"
        fewer = qr(["a", "b"], [[1, 2]])
        period = item("1", correct=False, tags=("period",))
        assert categorize_failure(period, fewer, expected) == "wrong period"
        joined = item("1", correct=False, tags=("join",))
        assert categorize_failure(joined, fewer, expected) == "wrong join"
        assert categorize_failure(item("1", correct=False), fewer, expected) == "wrong filter"
        same_shape = qr(["a", "b"], [[1, 9], [3, 4]])
        assert (
            categorize_failure(item("1", correct=False), same_shape, expected)
            == "wrong aggregation"
        )
