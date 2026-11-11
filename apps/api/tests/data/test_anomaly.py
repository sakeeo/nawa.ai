import pytest

from nawa.data.anomaly import Anomaly, detect_anomalies, zscore_anomalies


def months(values: list[float]) -> list[tuple[str, float]]:
    return [(f"2025-{i + 1:02d}-01", value) for i, value in enumerate(values)]


def test_an_obvious_outlier_is_found_with_its_direction() -> None:
    found = zscore_anomalies(months([100, 102, 98, 101, 99, 100, 40, 101]))
    assert [a.label for a in found] == ["2025-07-01"]
    assert found[0].direction == "low" and found[0].z < -2
    high = zscore_anomalies(months([100, 102, 98, 101, 99, 100, 300, 101]))
    assert high[0].direction == "high" and high[0].value == 300


def test_a_flat_or_gently_varying_series_has_no_anomaly() -> None:
    assert zscore_anomalies(months([5, 5, 5, 5, 5, 5, 5])) == []
    assert zscore_anomalies(months([100, 101, 99, 100, 102, 98, 100])) == []


def test_too_few_points_give_nothing() -> None:
    assert zscore_anomalies(months([1, 1, 1, 1, 100])) == []  # 5 points
    assert zscore_anomalies(months([1, 1, 1, 1, 100]), min_points=5) != []
    assert zscore_anomalies([]) == []


def test_the_threshold_is_respected() -> None:
    series = months([100, 102, 98, 101, 99, 100, 80, 101])
    assert (
        zscore_anomalies(series, threshold=2.0) != []
        or zscore_anomalies(series, threshold=3.0) == []
    )
    strict = zscore_anomalies(series, threshold=10.0)
    assert strict == []
    loose = zscore_anomalies(series, threshold=0.5)
    assert len(loose) > len(zscore_anomalies(series, threshold=2.0))


def test_results_are_ordered_by_strength_then_label_and_are_deterministic() -> None:
    series = months([100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 10, 190])
    first = zscore_anomalies(series, threshold=1.0)
    assert first == zscore_anomalies(list(reversed(series)), threshold=1.0)
    strengths = [abs(a.z) for a in first]
    assert strengths == sorted(strengths, reverse=True)
    tied = zscore_anomalies(
        [
            ("b", 0.0),
            ("a", 0.0),
            ("c", 10.0),
            ("d", 10.0),
            ("e", 5.0),
            ("f", 5.0),
            ("g", 5.0),
            ("h", 5.0),
        ],
        threshold=0.1,
    )
    same_strength = [a for a in tied if abs(abs(a.z) - abs(tied[0].z)) < 1e-9]
    assert [a.label for a in same_strength] == sorted(a.label for a in same_strength)


def test_values_are_rounded_to_two_decimals() -> None:
    found = zscore_anomalies(months([100, 102, 98, 101, 99, 100, 40, 101]))
    assert found[0].z == round(found[0].z, 2)


def test_anomaly_is_immutable() -> None:
    found = Anomaly("x", 1.0, 2.5, "high")
    with pytest.raises(AttributeError):
        found.z = 0  # type: ignore[misc]


COLUMNS = ["month", "revenue"]


def test_detect_reads_a_time_series_out_of_a_result() -> None:
    rows: list[list[object]] = [
        [f"2025-{i:02d}-01T00:00:00", v]
        for i, v in enumerate([100, 102, 98, 101, 99, 100, 40, 101], 1)
    ]
    found = detect_anomalies(COLUMNS, rows)
    assert [(a.label, a.direction) for a in found] == [("2025-07-01", "low")]


def test_detect_skips_nulls_and_sorts_by_time() -> None:
    rows: list[list[object]] = [
        ["2025-08-01", 101],
        ["2025-07-01", 40],
        ["2025-06-01", 100],
        ["2025-05-01", None],
        ["2025-04-01", 99],
        ["2025-03-01", 101],
        ["2025-02-01", 98],
        ["2025-01-01", 102],
    ]
    assert [a.label for a in detect_anomalies(COLUMNS, rows)] == ["2025-07-01"]


@pytest.mark.parametrize(
    ("columns", "rows"),
    [
        (
            ["outlet", "revenue"],
            [[f"o{i}", v] for i, v in enumerate([100, 102, 98, 101, 99, 100, 40, 101])],
        ),
        (
            ["month", "outlet", "revenue"],
            [
                [f"2025-{i:02d}-01", "A", v]
                for i, v in enumerate([100, 102, 98, 101, 99, 100, 40, 101], 1)
            ],
        ),
        (["month"], [[f"2025-{i:02d}-01"] for i in range(1, 9)]),
        (["revenue"], [[v] for v in [100, 102, 98, 101, 99, 100, 40, 101]]),
    ],
)
def test_detect_only_looks_at_one_temporal_axis_with_a_number(
    columns: list[str], rows: list[list[object]]
) -> None:
    assert detect_anomalies(columns, rows) == []
