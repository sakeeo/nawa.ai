from pathlib import Path

import pytest
from noesantara_seed.load import TABLES

from nawa.data.discovery import ColumnInfo, ForeignKey, TableInfo
from nawa.data.semantic import (
    SemanticError,
    allowlist,
    draft_from_schema,
    parse_semantic_yaml,
    to_yaml,
    validate_against_schema,
)

DEMO_YAML = Path(__file__).resolve().parents[4] / "seed" / "noesantara_semantic.yaml"


def _seed_schema() -> list[TableInfo]:
    return [
        TableInfo(
            name=table,
            columns=[ColumnInfo(c, "text", True) for c in columns],
            primary_key=[],
            foreign_keys=[],
            row_estimate=0,
        )
        for table, columns in TABLES
    ]


def _schema() -> list[TableInfo]:
    return [
        TableInfo(
            "outlets",
            [ColumnInfo("id", "integer", False), ColumnInfo("name", "text", False)],
            ["id"],
            [],
            3,
        ),
        TableInfo(
            "orders",
            [
                ColumnInfo("id", "integer", False),
                ColumnInfo("outlet_id", "integer", False),
                ColumnInfo("amount", "numeric", True),
                ColumnInfo("created_at", "timestamp", False),
            ],
            ["id"],
            [ForeignKey(["outlet_id"], "outlets", ["id"])],
            40,
        ),
    ]


BASE = """
tables:
  outlets:
    columns: [id, name]
  orders:
    columns: [id, outlet_id, amount, created_at]
metrics:
  revenue:
    sql: SUM(orders.amount)
dimensions:
  outlet: outlets.name
joins:
  - orders.outlet_id = outlets.id
"""


def _problems(yaml_text: str) -> list[str]:
    return validate_against_schema(parse_semantic_yaml(yaml_text), _schema())


def test_shipped_demo_model_parses_and_validates_against_the_seed_schema() -> None:
    model = parse_semantic_yaml(DEMO_YAML.read_text(encoding="utf-8"))
    assert validate_against_schema(model, _seed_schema()) == []
    assert {m.name for m in model.metrics} >= {"revenue", "gross_profit", "average_order_value"}
    assert {d.name for d in model.dimensions} >= {"outlet", "channel", "menu_category", "month"}
    assert model.time_anchor is not None


def test_demo_allowlist_omits_the_pii_column_but_keeps_the_rest() -> None:
    model = parse_semantic_yaml(DEMO_YAML.read_text(encoding="utf-8"))
    allowed = allowlist(model)
    assert "name" not in allowed["customers"]
    assert allowed["customers"] == {"id", "outlet_id"}
    assert set(allowed) == {table for table, _ in TABLES}
    full = dict(TABLES)
    for table, columns in allowed.items():
        if table != "customers":
            assert columns == set(full[table]), table


def test_valid_model_has_no_problems() -> None:
    assert _problems(BASE) == []


def test_unknown_top_level_and_nested_keys_are_rejected() -> None:
    with pytest.raises(SemanticError):
        parse_semantic_yaml(BASE + "\nsurprise: 1\n")
    with pytest.raises(SemanticError):
        parse_semantic_yaml(BASE.replace("sql: SUM(orders.amount)", "sql: SUM(1)\n    extra: x"))


def test_unknown_table_and_column_are_reported() -> None:
    problems = _problems(
        BASE.replace("orders:\n    columns: [id,", "orders:\n    columns: [ghost, id,")
    )
    assert any("ghost" in p for p in problems)
    problems = _problems(
        BASE.replace(
            "  outlets:\n    columns: [id, name]",
            "  outlets:\n    columns: [id, name]\n  phantom:\n    columns: [id]",
        )
    )
    assert any("phantom" in p for p in problems)


def test_sensitive_columns_are_excluded_from_the_allowlist() -> None:
    text = BASE.replace(
        "columns: [id, name]", "columns:\n      - id\n      - {name: name, sensitive: true}"
    )
    allowed = allowlist(parse_semantic_yaml(text))
    assert allowed["outlets"] == {"id"}
    assert allowed["orders"] == {"id", "outlet_id", "amount", "created_at"}


def test_metric_using_a_sensitive_or_omitted_column_is_reported() -> None:
    sensitive = BASE.replace(
        "columns: [id, name]", "columns:\n      - id\n      - {name: name, sensitive: true}"
    ).replace("outlet: outlets.name", "outlet: outlets.id")
    problems = _problems(sensitive.replace("SUM(orders.amount)", "COUNT(outlets.name)"))
    assert any("outlets.name" in p for p in problems)
    omitted = BASE.replace(
        "columns: [id, outlet_id, amount, created_at]", "columns: [id, outlet_id, created_at]"
    )
    problems = _problems(omitted)
    assert any("orders.amount" in p for p in problems)


def test_metric_syntax_error_and_non_expressions_are_reported() -> None:
    assert any(
        "revenue" in p for p in _problems(BASE.replace("SUM(orders.amount)", "SUM(orders.amount"))
    )
    assert any(
        "revenue" in p for p in _problems(BASE.replace("SUM(orders.amount)", "DROP TABLE orders"))
    )
    assert any(
        "revenue" in p
        for p in _problems(BASE.replace("SUM(orders.amount)", "(SELECT 1 FROM orders)"))
    )


def test_metrics_may_reference_each_other_but_not_unknown_names_or_themselves() -> None:
    chained = BASE.replace(
        "metrics:\n  revenue:\n    sql: SUM(orders.amount)",
        "metrics:\n  revenue:\n    sql: SUM(orders.amount)\n"
        "  per_order:\n    sql: revenue / NULLIF(COUNT(orders.id), 0)",
    )
    assert _problems(chained) == []
    unknown = chained.replace("revenue / NULLIF", "mystery / NULLIF")
    assert any("mystery" in p for p in _problems(unknown))
    cyclic = BASE.replace("sql: SUM(orders.amount)", "sql: revenue + 1")
    assert any("revenue" in p for p in _problems(cyclic))


def test_joins_must_reference_listed_tables_and_columns() -> None:
    assert any(
        "ghost" in p
        for p in _problems(
            BASE.replace("- orders.outlet_id = outlets.id", "- orders.outlet_id = ghost.id")
        )
    )
    assert any("nope" in p for p in _problems(BASE.replace("orders.outlet_id =", "orders.nope =")))


def test_join_must_be_a_column_equality() -> None:
    for bad in (
        "orders.outlet_id > outlets.id",
        "orders.outlet_id",
        "1 = 1",
        "orders.a = orders.b",
    ):
        with pytest.raises(SemanticError):
            parse_semantic_yaml(BASE.replace("orders.outlet_id = outlets.id", bad))


def test_time_anchor_must_be_one_select_over_listed_tables() -> None:
    ok = BASE + "time_anchor: SELECT MAX(created_at)::date FROM orders\n"
    assert _problems(ok) == []
    for bad in (
        "DROP TABLE orders",
        "SELECT 1; SELECT 2",
        "SELECT MAX(x) FROM ghost",
        "SELECT MAX(missing_col) FROM orders",
        "UPDATE orders SET amount = 0",
    ):
        assert _problems(BASE + f"time_anchor: {bad!r}\n"), bad


def test_duplicate_keys_in_yaml_are_an_error_not_a_silent_overwrite() -> None:
    duplicated = BASE.replace(
        "metrics:\n  revenue:\n    sql: SUM(orders.amount)",
        "metrics:\n  revenue:\n    sql: SUM(orders.amount)\n  revenue:\n    sql: SUM(1)",
    )
    with pytest.raises(SemanticError) as info:
        parse_semantic_yaml(duplicated)
    assert "revenue" in str(info.value)


def test_names_must_be_plain_identifiers() -> None:
    for name in ("my metric", "x;DROP", 'q"uote', "1abc"):
        with pytest.raises(SemanticError):
            parse_semantic_yaml(BASE.replace("revenue:", f"{name!r}:"))


def test_yaml_loading_is_safe() -> None:
    with pytest.raises(SemanticError):
        parse_semantic_yaml("!!python/object/apply:os.system ['echo pwned']")


@pytest.mark.parametrize("text", ["", "- a\n- b", "just a string", "tables: 5"])
def test_non_mapping_or_malformed_documents_raise_semantic_error(text: str) -> None:
    with pytest.raises(SemanticError):
        parse_semantic_yaml(text)


def test_draft_from_schema_covers_every_table_column_and_foreign_key() -> None:
    draft = draft_from_schema(_schema())
    assert {t.name for t in draft.tables} == {"outlets", "orders"}
    orders = next(t for t in draft.tables if t.name == "orders")
    assert [c.name for c in orders.columns] == ["id", "outlet_id", "amount", "created_at"]
    assert [(j.left, j.right, j.on) for j in draft.joins] == [
        ("orders", "outlets", "orders.outlet_id = outlets.id")
    ]
    assert draft.metrics == [] and draft.dimensions == [] and draft.time_anchor is None
    assert validate_against_schema(draft, _schema()) == []


def test_yaml_round_trip_is_lossless() -> None:
    for model in (
        draft_from_schema(_schema()),
        parse_semantic_yaml(DEMO_YAML.read_text(encoding="utf-8")),
        parse_semantic_yaml(BASE),
    ):
        assert parse_semantic_yaml(to_yaml(model)) == model
