from pathlib import Path

import pytest

from nawa.evaluation.sql_report import (
    ANALYSIS_END,
    ANALYSIS_START,
    TARGETS,
    SqlArmResult,
    extract_analysis,
    load_results,
    render,
    save_result,
)


def arm(name: str, accuracy: float = 0.9, **overrides: object) -> SqlArmResult:
    base: dict[str, object] = dict(
        name=name,
        group="ablation",
        status="ok",
        reason="",
        config={"name": name, "schema_linking": True, "self_correction": True},
        metrics={
            "execution_accuracy": accuracy,
            "valid_sql_rate": 0.97,
            "self_correction_recovery_rate": 0.5,
            "dangerous_blocked_rate": 1.0,
            "insight_groundedness": 0.96,
            "p50_latency_ms": 2100.0,
            "p95_latency_ms": 5200.0,
            "p50_insight_ms": 900.0,
        },
        by_difficulty={
            "easy": {"count": 20, "execution_accuracy": 0.95, "valid_sql_rate": 1.0},
            "medium": {"count": 20, "execution_accuracy": 0.85, "valid_sql_rate": 0.95},
            "hard": {"count": 10, "execution_accuracy": 0.6, "valid_sql_rate": 0.9},
        },
        counts={"answerable": 50, "dangerous": 10, "errors": 0},
        items=[
            {
                "id": "H01",
                "difficulty": "hard",
                "question": "Outlet mana terendah?",
                "status": "ok",
                "sql": "SELECT outlets.name FROM outlets",
                "attempts": 1,
                "correct": False,
                "category": "wrong period",
                "error": None,
            },
            {
                "id": "E01",
                "difficulty": "easy",
                "question": "Berapa outlet?",
                "status": "ok",
                "sql": "SELECT COUNT(*) FROM outlets",
                "attempts": 1,
                "correct": True,
                "category": None,
                "error": None,
            },
        ],
        git_commit="abc1234",
        models={"generator": "deepseek/deepseek-chat", "embedding": "ollama/bge-m3"},
        litellm_version="1.0",
        started_at="2026-11-10T10:00:00+00:00",
    )
    base.update(overrides)
    return SqlArmResult(**base)  # type: ignore[arg-type]


def test_targets_match_the_master_plan() -> None:
    assert TARGETS["execution_accuracy"] == (0.80, ">=")
    assert TARGETS["valid_sql_rate"] == (0.95, ">=")
    assert TARGETS["dangerous_blocked_rate"] == (1.0, ">=")
    assert TARGETS["insight_groundedness"] == (0.95, ">=")
    assert TARGETS["p95_latency_ms"] == (8000.0, "<")


def test_the_targets_table_marks_each_target_met_or_missed() -> None:
    markdown = render([arm("baseline", accuracy=0.9)], baseline="baseline")
    assert "## Targets" in markdown
    row = next(line for line in markdown.splitlines() if line.startswith("| Execution accuracy"))
    assert "0.900" in row and "≥ 0.8" in row and "met" in row.lower()
    missed = render([arm("baseline", accuracy=0.7)], baseline="baseline")
    row = next(line for line in missed.splitlines() if line.startswith("| Execution accuracy"))
    assert "missed" in row.lower()
    latency = next(line for line in markdown.splitlines() if line.startswith("| P95 latency"))
    assert "5200 ms" in latency and "< 8000" in latency
    slow = render(
        [arm("baseline", metrics={**arm("x").metrics, "p95_latency_ms": 9000.0})],
        baseline="baseline",
    )
    assert (
        "missed"
        in next(line for line in slow.splitlines() if line.startswith("| P95 latency")).lower()
    )


def test_recovery_is_reported_without_a_target() -> None:
    markdown = render([arm("baseline")], baseline="baseline")
    row = next(
        line for line in markdown.splitlines() if line.startswith("| Self-correction recovery")
    )
    assert "0.500" in row and "reported" in row.lower()
    none = render(
        [arm("baseline", metrics={**arm("x").metrics, "self_correction_recovery_rate": None})],
        baseline="baseline",
    )
    assert "no item needed" in none.lower()


def test_there_is_a_difficulty_table_for_the_baseline() -> None:
    markdown = render([arm("baseline")], baseline="baseline")
    assert "## Results by difficulty" in markdown
    for needle in ("| easy | 20 | 0.950", "| medium | 20 | 0.850", "| hard | 10 | 0.600"):
        assert needle in markdown


def test_ablation_arms_are_compared_side_by_side() -> None:
    arms = [arm("baseline", 0.9), arm("no-linking", 0.8), arm("no-correction", 0.85)]
    markdown = render(arms, baseline="baseline")
    assert "## Ablations" in markdown
    for name in ("baseline", "no-linking", "no-correction"):
        assert f"| {name} |" in markdown
    assert "0.800" in markdown


def test_skipped_and_failed_arms_show_their_reason_instead_of_numbers() -> None:
    skipped = arm(
        "gen-local",
        status="skipped",
        reason="needs OLLAMA",
        metrics={},
        items=[],
        by_difficulty={},
        counts={},
    )
    markdown = render([arm("baseline"), skipped], baseline="baseline")
    assert "gen-local" in markdown and "needs OLLAMA" in markdown


def test_failure_analysis_lists_the_failed_items_with_their_category() -> None:
    markdown = render([arm("baseline")], baseline="baseline")
    assert "## Failure analysis" in markdown
    assert "H01" in markdown and "wrong period" in markdown
    assert "E01" not in markdown.split("## Failure analysis", 1)[1].split("## ", 1)[0]
    assert "wrong period: 1" in markdown  # summary by category


def test_author_notes_survive_regeneration() -> None:
    first = render([arm("baseline")], baseline="baseline")
    assert ANALYSIS_START in first and ANALYSIS_END in first
    written = first.replace(
        "_Not written yet: add the analysis from the real numbers._",
        "Model keeps mixing up months.",
    )
    assert extract_analysis(written) == "Model keeps mixing up months."
    again = render([arm("baseline")], baseline="baseline", analysis=extract_analysis(written))
    assert "Model keeps mixing up months." in again
    assert extract_analysis(first) == ""  # the placeholder is not an analysis


def test_limitations_are_stated_honestly() -> None:
    markdown = render([arm("baseline")], baseline="baseline")
    assert "## Limitations" in markdown
    assert "50" in markdown and "one item" in markdown.lower()


def test_the_setup_block_records_commit_models_and_dataset() -> None:
    markdown = render([arm("baseline")], baseline="baseline")
    assert "abc1234" in markdown and "deepseek/deepseek-chat" in markdown
    assert "50 answerable" in markdown and "10 dangerous" in markdown


def test_results_round_trip_through_json_files(tmp_path: Path) -> None:
    original = arm("baseline")
    path = save_result(original, tmp_path)
    assert path.name == "sql-baseline.json"
    assert load_results(tmp_path) == [original]
    assert load_results(tmp_path / "missing") == []


def test_rendering_without_results_or_without_the_baseline_is_an_error() -> None:
    with pytest.raises(ValueError, match="no results"):
        render([], baseline="baseline")
    with pytest.raises(ValueError, match="baseline"):
        render([arm("other")], baseline="baseline")
    with pytest.raises(ValueError, match="baseline"):
        render([arm("baseline", status="skipped", reason="x")], baseline="baseline")


def test_the_report_states_whether_the_target_database_was_left_unchanged() -> None:
    intact = render(
        [arm("baseline", metrics={**arm("x").metrics, "database_intact": True})],
        baseline="baseline",
    )
    assert "unchanged after the run: yes" in intact
    changed = render(
        [arm("baseline", metrics={**arm("x").metrics, "database_intact": False})],
        baseline="baseline",
    )
    assert "NO, the data changed" in changed
    assert "unchanged after the run" not in render([arm("baseline")], baseline="baseline")
