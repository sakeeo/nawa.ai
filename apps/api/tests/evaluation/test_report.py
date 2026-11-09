from pathlib import Path

import pytest

from nawa.evaluation.experiments import (
    Arm,
    ArmResult,
    Experiment,
    ExperimentResult,
    SweepRow,
    load_experiments,
    load_result,
    pick_threshold,
    run_experiment,
    save_result,
    sweep_threshold,
)
from nawa.evaluation.report import (
    ANALYSIS_PLACEHOLDER,
    extract_analysis,
    render,
    render_charts,
)
from nawa.evaluation.runner import EvalConfigError, EvalRunSummary, RunConfig

FIXTURES = Path(__file__).parent / "fixtures"
REPO_EVALS = Path(__file__).resolve().parents[4] / "evals"


def _arm(name: str, **metrics: float) -> ArmResult:
    return ArmResult(
        name=name, status="ok", config={"name": name}, metrics=metrics, git_commit="abc1234"
    )


def _experiments() -> list[ExperimentResult]:
    skipped = ArmResult(
        name="embed-api",
        status="skipped",
        config={"name": "embed-api"},
        reason="MISTRAL_API_KEY not set",
    )
    return [
        ExperimentResult(
            "chunking",
            "Chunking strategy",
            ("recall_at_5", "faithfulness"),
            [
                _arm("chunk-fixed", recall_at_5=0.8, faithfulness=0.9),
                _arm("chunk-heading", recall_at_5=0.9, faithfulness=0.9),
            ],
        ),
        ExperimentResult(
            "embedding",
            "Embedding model",
            ("recall_at_5", "p50_plan_ms"),
            [_arm("embed-local", recall_at_5=0.875, p50_plan_ms=120.4), skipped],
            note="API arm sends synthetic documents only.",
        ),
    ]


def _render(**overrides: object) -> str:
    sweep = sweep_threshold(
        [("answerable", 0.6), ("answerable", 0.5), ("unanswerable", 0.2), ("unanswerable", 0.45)],
        stop=0.6,
        step=0.2,
    )
    args: dict[str, object] = {
        "setup": {"Commit": "abc1234", "Dataset": "4 items"},
        "experiments": _experiments(),
        "sweep": sweep,
        "chosen": pick_threshold(sweep, min_answerable_recall=1.0),
        "min_answerable_recall": 1.0,
        "final": _arm(
            "chunk-heading",
            recall_at_5=0.9,
            mrr=0.65,
            faithfulness=0.95,
            citation_accuracy=0.9,
            correct_refusal_rate=1.0,
            injection_resistance=1.0,
            p95_ttft_ms=3500.0,
        ),
        "limitations": ["Small dataset."],
        "analysis": "",
        "charts": list(render_charts(_experiments())),
    }
    args.update(overrides)
    return render(**args)  # type: ignore[arg-type]


def test_render_matches_the_golden_file() -> None:
    expected = (FIXTURES / "report_expected.md").read_text(encoding="utf-8")
    assert _render() == expected


def test_render_is_deterministic() -> None:
    assert _render() == _render()


def test_missed_targets_are_labelled_with_their_delta() -> None:
    text = _render()
    assert "| MRR | >= 0.700 | 0.650 | missed (-0.050) |" in text
    assert "| p95 time to first token | < 3000 ms | 3500 ms | missed (+500 ms) |" in text
    assert "| Recall@5 | >= 0.850 | 0.900 | met |" in text
    assert "Missed targets: MRR, p95 time to first token." in text


def test_skipped_arm_shows_the_reason_not_a_zero() -> None:
    row = next(line for line in _render().splitlines() if line.startswith("| `embed-api`"))
    assert "skipped: MISTRAL_API_KEY not set" in row
    assert "0.000" not in row
    assert row.count("n/a") == 2


def test_numbers_use_three_decimals_and_milliseconds() -> None:
    text = _render()
    assert "| `embed-local` | 0.875 | 120 ms | ok |" in text


def test_missing_final_run_is_stated() -> None:
    text = _render(final=None)
    assert "No complete run of the final configuration is available." in text


def test_analysis_is_kept_across_regeneration() -> None:
    first = _render()
    assert ANALYSIS_PLACEHOLDER in first
    assert extract_analysis(first) == ""
    written = first.replace(ANALYSIS_PLACEHOLDER, "Heading chunks won by 0.100 Recall@5.")
    assert extract_analysis(written) == "Heading chunks won by 0.100 Recall@5."
    assert "Heading chunks won" in _render(analysis=extract_analysis(written))


def test_charts_need_two_scored_arms() -> None:
    charts = render_charts(_experiments())
    assert list(charts) == ["eval-chunking.svg"]  # embedding has one scored arm
    assert charts["eval-chunking.svg"].startswith("<svg")
    assert "0.900" in charts["eval-chunking.svg"]


def test_sweep_and_pick_threshold() -> None:
    samples = [
        ("answerable", 0.9),
        ("answerable", 0.6),
        ("answerable", 0.4),
        ("unanswerable", 0.1),
        ("unanswerable", 0.3),
        ("unanswerable", None),
        ("injection", 0.9),  # ignored
    ]
    rows = sweep_threshold(samples, stop=0.8, step=0.1)
    at = {r.threshold: r for r in rows}
    assert at[0.0].correct_refusal_rate == pytest.approx(1 / 3)  # only "no candidates" refuses
    assert at[0.5] == SweepRow(0.5, 3 / 4, 1.0, 2 / 3)
    best = pick_threshold(rows, min_answerable_recall=1.0)
    assert best is not None
    assert best.threshold == 0.4  # the only row refusing everything while answering all
    assert best.correct_refusal_rate == 1.0
    assert pick_threshold(rows[-1:], min_answerable_recall=0.99) is None


async def test_run_experiment_skips_missing_keys_and_survives_arm_failures() -> None:
    calls: list[str] = []

    async def fake_run(config: RunConfig) -> EvalRunSummary:
        calls.append(config.name)
        if config.name == "boom":
            raise RuntimeError("ollama down")
        if config.name == "norerank":
            raise EvalConfigError("use_rerank needs RERANKER_ENABLED")
        import uuid

        return EvalRunSummary(uuid.uuid4(), {}, {"recall_at_5": 0.5}, {"items": 1})

    exp = Experiment(
        "x",
        "X",
        ("recall_at_5",),
        (
            Arm(RunConfig("ok")),
            Arm(RunConfig("api"), requires_env=("SOME_KEY",)),
            Arm(RunConfig("boom")),
            Arm(RunConfig("norerank")),
        ),
    )
    result = await run_experiment(
        exp, fake_run, env={}, default_models={"generator": "g", "embedding": "e"}, commit="abc"
    )
    by_name = {a.name: a for a in result.arms}
    assert calls == ["ok", "boom", "norerank"]
    assert by_name["ok"].status == "ok" and by_name["ok"].metrics == {"recall_at_5": 0.5}
    assert by_name["ok"].git_commit == "abc"
    assert by_name["ok"].models["generator"] == "g"
    assert by_name["api"].status == "skipped" and by_name["api"].reason == "SOME_KEY not set"
    assert by_name["boom"].status == "error" and "ollama down" in by_name["boom"].reason
    assert by_name["norerank"].status == "skipped"


def test_results_roundtrip_through_json(tmp_path: Path) -> None:
    original = _experiments()[1]
    loaded = load_result(save_result(original, tmp_path))
    assert loaded == original


def test_shipped_experiments_file_defines_the_five_experiments() -> None:
    experiments = load_experiments(REPO_EVALS / "experiments.yaml")
    assert [e.name for e in experiments] == [
        "chunking",
        "retrieval",
        "reranking",
        "embedding",
        "generator",
    ]
    names = [a.config.name for e in experiments for a in e.arms]
    assert len(names) == len(set(names))
    assert {"retrieval-hybrid", "chunk-heading"} <= set(names)
