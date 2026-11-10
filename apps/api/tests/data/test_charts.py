from nawa.data.charts import ChartSpec, choose_chart, column_kinds


def test_one_row_with_one_number_is_a_kpi() -> None:
    spec = choose_chart(["revenue"], [[1234567.5]])
    assert spec == ChartSpec("kpi", None, ["revenue"], "revenue")


def test_one_row_with_a_label_and_a_number_is_still_a_kpi() -> None:
    spec = choose_chart(["outlet", "revenue"], [["Bandung", 100]])
    assert spec.kind == "kpi" and spec.y == ["revenue"]


def test_a_date_column_with_a_number_is_a_line() -> None:
    rows = [["2025-06-01T00:00:00", 10], ["2025-07-01T00:00:00", 12], ["2025-08-01T00:00:00", 7]]
    spec = choose_chart(["month", "revenue"], rows)
    assert (spec.kind, spec.x, spec.y) == ("line", "month", ["revenue"])


def test_two_numeric_series_over_time_are_one_line_chart() -> None:
    rows = [["2025-06-01", 10, 4], ["2025-07-01", 12, 5]]
    spec = choose_chart(["month", "revenue", "profit"], rows)
    assert (spec.kind, spec.y) == ("line", ["revenue", "profit"])


def test_a_category_with_a_number_is_a_bar() -> None:
    rows = [[name, i * 10] for i, name in enumerate(["A", "B", "C", "D", "E"])]
    spec = choose_chart(["outlet", "revenue"], rows)
    assert (spec.kind, spec.x, spec.y) == ("bar", "outlet", ["revenue"])
    assert "revenue" in spec.title and "outlet" in spec.title


def test_more_than_twenty_categories_fall_back_to_a_table() -> None:
    rows = [[f"menu {i}", i] for i in range(25)]
    assert choose_chart(["menu", "qty"], rows).kind == "table"
    assert choose_chart(["menu", "qty"], rows[:20]).kind == "bar"


def test_zero_rows_is_a_table() -> None:
    assert choose_chart(["a", "b"], []).kind == "table"


def test_text_only_and_number_only_results_are_tables() -> None:
    assert choose_chart(["name", "city"], [["a", "x"], ["b", "y"]]).kind == "table"
    assert choose_chart(["id", "amount"], [[1, 5], [2, 6]]).kind == "table"


def test_two_label_columns_are_ambiguous_so_a_table() -> None:
    rows = [["A", "dine_in", 5], ["A", "delivery", 6], ["B", "dine_in", 7]]
    assert choose_chart(["outlet", "channel", "revenue"], rows).kind == "table"


def test_more_than_three_series_fall_back_to_a_table() -> None:
    rows = [["2025-01-01", 1, 2, 3, 4], ["2025-02-01", 1, 2, 3, 4]]
    assert choose_chart(["m", "a", "b", "c", "d"], rows).kind == "table"


def test_nulls_do_not_change_the_column_kind() -> None:
    kinds = column_kinds(
        ["label", "n", "d", "nothing"], [["a", None, "2025-01-01", None], [None, 3, None, None]]
    )
    assert kinds == {"label": "categorical", "n": "numeric", "d": "temporal", "nothing": "empty"}


def test_booleans_and_numeric_strings_are_not_numbers() -> None:
    kinds = column_kinds(["flag", "huge"], [[True, "12345678901234567890.5"], [False, "1.5"]])
    assert kinds == {"flag": "categorical", "huge": "categorical"}


def test_a_date_only_result_is_a_table() -> None:
    assert choose_chart(["d"], [["2025-01-01"], ["2025-01-02"]]).kind == "table"
