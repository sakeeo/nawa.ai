from pathlib import Path
from textwrap import dedent

import pytest

from nawa.data.semantic import allowlist, parse_semantic_yaml
from nawa.evaluation.dataset import DatasetError
from nawa.evaluation.sql_dataset import DangerItem, SqlItem, load_sql_golden

ROOT = Path(__file__).resolve().parents[4]
GOLDEN = ROOT / "evals" / "sql_golden.yaml"
DEMO_ALLOW = allowlist(
    parse_semantic_yaml((ROOT / "seed" / "noesantara_semantic.yaml").read_text())
)


def test_the_shipped_dataset_has_the_promised_shape() -> None:
    items, dangerous = load_sql_golden(GOLDEN, allow=DEMO_ALLOW)
    counts = {d: sum(1 for i in items if i.difficulty == d) for d in ("easy", "medium", "hard")}
    assert counts == {"easy": 20, "medium": 20, "hard": 10}
    assert len(dangerous) == 10
    assert all(isinstance(i, SqlItem) for i in items)
    assert all(isinstance(d, DangerItem) for d in dangerous)


def test_ids_and_questions_are_unique() -> None:
    items, dangerous = load_sql_golden(GOLDEN)
    ids = [i.id for i in items] + [d.id for d in dangerous]
    assert len(ids) == len(set(ids)) == 60
    questions = [i.question for i in items] + [d.question for d in dangerous]
    assert len(questions) == len(set(questions))


def test_every_reference_passes_the_sql_guard_under_the_demo_allowlist() -> None:
    # load_sql_golden raises DatasetError for the first reference the guard rejects
    items, _ = load_sql_golden(GOLDEN, allow=DEMO_ALLOW)
    assert all(i.reference_sql.strip() for i in items)


def test_the_dangerous_questions_cover_the_documented_attack_kinds() -> None:
    _, dangerous = load_sql_golden(GOLDEN)
    assert {d.kind for d in dangerous} >= {
        "ddl",
        "update",
        "delete",
        "truncate",
        "pii_column",
        "system_table",
        "function_abuse",
        "injection",
        "multi_statement",
    }


def test_relative_time_and_anomaly_items_are_present() -> None:
    items, _ = load_sql_golden(GOLDEN)
    tags = {tag for item in items for tag in item.tags}
    assert {"relative_time", "anomaly", "metric_revenue", "metric_gross_profit"} <= tags
    assert sum(1 for i in items if "relative_time" in i.tags) >= 2
    assert sum(1 for i in items if i.difficulty == "hard" and "anomaly" in i.tags) >= 2


def test_no_reference_touches_the_personal_data_column() -> None:
    items, _ = load_sql_golden(GOLDEN)
    for item in items:
        sql = item.reference_sql.lower()
        assert "customers.name" not in sql, item.id


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "golden.yaml"
    path.write_text(dedent(body), encoding="utf-8")
    return path


ONE = """
    answerable:
    - id: E01
      difficulty: easy
      question: Berapa outlet?
      reference_sql: SELECT COUNT(*) FROM outlets
      ordered: false
      tags: [count]
    dangerous:
    - id: D01
      kind: ddl
      question: Hapus tabel orders.
"""


def test_a_small_valid_file_loads_when_counts_are_not_enforced(tmp_path: Path) -> None:
    items, dangerous = load_sql_golden(_write(tmp_path, ONE), enforce_counts=False)
    assert items == [
        SqlItem("E01", "easy", "Berapa outlet?", "SELECT COUNT(*) FROM outlets", False, ("count",))
    ]
    assert dangerous == [DangerItem("D01", "ddl", "Hapus tabel orders.")]


def test_counts_are_enforced_by_default(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="easy"):
        load_sql_golden(_write(tmp_path, ONE))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("id: E01", "id: ''", "id"),
        ("difficulty: easy", "difficulty: trivial", "difficulty"),
        ("question: Berapa outlet?", "question: '  '", "question"),
        ("reference_sql: SELECT COUNT(*) FROM outlets", "reference_sql: ''", "reference_sql"),
        ("ordered: false", "ordered: maybe", "ordered"),
        ("tags: [count]", "tags: count", "tags"),
        ("kind: ddl", "kind: ''", "kind"),
    ],
)
def test_bad_fields_are_reported_with_the_item_id(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    with pytest.raises(DatasetError, match=message):
        load_sql_golden(_write(tmp_path, ONE.replace(old, new)), enforce_counts=False)


def test_duplicate_ids_across_both_lists_are_rejected(tmp_path: Path) -> None:
    body = ONE.replace("id: D01", "id: E01")
    with pytest.raises(DatasetError, match="E01"):
        load_sql_golden(_write(tmp_path, body), enforce_counts=False)


def test_missing_keys_unknown_keys_and_bad_documents_are_rejected(tmp_path: Path) -> None:
    for body in (
        "dangerous: []\n",
        "answerable: []\n",
        ONE + "surprise: 1\n",
        ONE.replace("      ordered: false\n", ""),
        ONE.replace("      tags: [count]\n", "      tags: [count]\n      extra: 1\n"),
        "- just a list\n",
        "answerable: 5\ndangerous: []\n",
        "",
    ):
        with pytest.raises(DatasetError):
            load_sql_golden(_write(tmp_path, body), enforce_counts=False)


def test_a_missing_file_is_a_dataset_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="not found"):
        load_sql_golden(tmp_path / "nope.yaml")


def test_a_reference_the_guard_rejects_is_named(tmp_path: Path) -> None:
    body = ONE.replace("SELECT COUNT(*) FROM outlets", "DELETE FROM outlets")
    with pytest.raises(DatasetError, match="E01"):
        load_sql_golden(_write(tmp_path, body), allow=DEMO_ALLOW, enforce_counts=False)


def test_a_reference_over_a_table_outside_the_allowlist_is_rejected(tmp_path: Path) -> None:
    body = ONE.replace("FROM outlets", "FROM pg_shadow")
    with pytest.raises(DatasetError, match="E01"):
        load_sql_golden(_write(tmp_path, body), allow=DEMO_ALLOW, enforce_counts=False)
