"""Experiment definitions, arm execution and the answer-vs-refuse threshold sweep."""

import importlib.metadata
import json
import os
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.db import apply_rls
from nawa.evaluation.runner import EvalConfigError, EvalRunSummary, RunConfig


@dataclass(frozen=True)
class Arm:
    config: RunConfig
    requires_env: tuple[str, ...] = ()


@dataclass(frozen=True)
class Experiment:
    name: str
    title: str
    metrics: tuple[str, ...]
    arms: tuple[Arm, ...]
    note: str = ""


@dataclass
class ArmResult:
    name: str
    status: str  # "ok" | "skipped" | "error"
    config: dict[str, Any]
    reason: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    run_id: str | None = None
    git_commit: str = ""
    models: dict[str, str] = field(default_factory=dict)
    litellm_version: str = ""
    # Generation sampling is left at provider defaults; no seed is set anywhere in the pipeline.
    seed: int | None = None


@dataclass
class ExperimentResult:
    name: str
    title: str
    metrics: tuple[str, ...]
    arms: list[ArmResult]
    note: str = ""


RunArm = Callable[[RunConfig], Awaitable[EvalRunSummary]]


def load_experiments(path: Path) -> list[Experiment]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    experiments: list[Experiment] = []
    seen: set[str] = set()
    for row in raw.get("experiments", []):
        name = str(row.get("name", ""))
        if not name or name in seen:
            raise EvalConfigError(f"duplicate or missing experiment name: {name!r}")
        seen.add(name)
        arms = tuple(
            Arm(RunConfig.from_dict(a["config"]), tuple(a.get("requires_env", ())))
            for a in row.get("arms", [])
        )
        if len(arms) < 2:
            raise EvalConfigError(f"experiment {name!r} needs at least two arms")
        experiments.append(
            Experiment(
                name=name,
                title=row.get("title", name),
                metrics=tuple(row.get("metrics", ())),
                arms=arms,
                note=row.get("note", ""),
            )
        )
    return experiments


def git_commit(cwd: Path | None = None) -> str:
    """`GIT_COMMIT` from the environment (the image has no checkout), else `git rev-parse`."""
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _litellm_version() -> str:
    try:
        return importlib.metadata.version("litellm")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


async def run_experiment(
    experiment: Experiment,
    run_arm: RunArm,
    *,
    env: Mapping[str, str],
    default_models: Mapping[str, str],
    commit: str,
) -> ExperimentResult:
    """Run every arm in order on the same golden set; a failing arm never hides the rest."""
    results: list[ArmResult] = []
    for arm in experiment.arms:
        config = asdict(arm.config)
        models = {
            "generator": arm.config.generator_model or default_models.get("generator", ""),
            "embedding": arm.config.embedding_model or default_models.get("embedding", ""),
            "judge": default_models.get("judge", "") if arm.config.judge_enabled else "",
        }
        base = ArmResult(
            name=arm.config.name,
            status="ok",
            config=config,
            git_commit=commit,
            models=models,
            litellm_version=_litellm_version(),
        )
        missing = [v for v in arm.requires_env if not env.get(v)]
        if missing:
            base.status = "skipped"
            base.reason = f"{', '.join(missing)} not set"
            results.append(base)
            continue
        try:
            summary = await run_arm(arm.config)
        except EvalConfigError as exc:
            base.status, base.reason = "skipped", str(exc)
        except Exception as exc:  # noqa: BLE001 - record and continue with the next arm
            base.status, base.reason = "error", f"{type(exc).__name__}: {exc}"
        else:
            base.metrics = dict(summary.metrics)
            base.counts = dict(summary.counts)
            base.run_id = str(summary.run_id)
        results.append(base)
    return ExperimentResult(
        experiment.name, experiment.title, experiment.metrics, results, experiment.note
    )


@dataclass(frozen=True)
class SweepRow:
    threshold: float
    refusal_precision: float  # refused items that were truly unanswerable
    correct_refusal_rate: float  # unanswerable items refused
    answerable_recall: float  # answerable items still answered


def sweep_threshold(
    samples: list[tuple[str, float | None]],
    *,
    start: float = 0.0,
    stop: float = 0.9,
    step: float = 0.05,
) -> list[SweepRow]:
    """Replay the relevance gate (answer iff best similarity >= threshold) over recorded samples.

    `samples` are (kind, best_similarity) for answerable and unanswerable items; no candidates
    (None) always refuses.
    """
    answerable = [s for k, s in samples if k == "answerable"]
    unanswerable = [s for k, s in samples if k == "unanswerable"]
    rows: list[SweepRow] = []
    steps = round((stop - start) / step)
    for i in range(steps + 1):
        t = round(start + i * step, 4)

        def answers(sim: float | None, t: float = t) -> bool:
            return sim is not None and sim >= t

        refused_un = sum(1 for s in unanswerable if not answers(s))
        refused_an = sum(1 for s in answerable if not answers(s))
        refused = refused_un + refused_an
        rows.append(
            SweepRow(
                threshold=t,
                refusal_precision=refused_un / refused if refused else 1.0,
                correct_refusal_rate=refused_un / len(unanswerable) if unanswerable else 0.0,
                answerable_recall=(
                    (len(answerable) - refused_an) / len(answerable) if answerable else 0.0
                ),
            )
        )
    return rows


def pick_threshold(rows: list[SweepRow], *, min_answerable_recall: float = 0.95) -> SweepRow | None:
    """Maximise Correct Refusal Rate subject to answerable recall >= target.

    Ties go to higher answerable recall, then to the lower threshold. None if no row qualifies.
    """
    feasible = [r for r in rows if r.answerable_recall >= min_answerable_recall]
    if not feasible:
        return None
    return max(feasible, key=lambda r: (r.correct_refusal_rate, r.answerable_recall, -r.threshold))


def save_result(result: ExperimentResult, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{result.name}.json"
    path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_result(path: Path) -> ExperimentResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    arms = [ArmResult(**a) for a in raw.pop("arms")]
    raw["metrics"] = tuple(raw["metrics"])
    return ExperimentResult(arms=arms, **raw)


async def load_samples(
    maker: async_sessionmaker[AsyncSession], run_id: str, kinds: Mapping[str, str]
) -> list[tuple[str, float | None]]:
    """(kind, best_similarity) of every answerable and unanswerable item in a stored run.

    `kinds` maps golden item id to kind.
    """
    async with maker() as session:
        await apply_rls(session, is_admin=True)
        rows = (
            await session.execute(
                text(
                    "SELECT question_id, metrics FROM eval_results"
                    " WHERE eval_run_id = CAST(:r AS uuid) ORDER BY question_id"
                ),
                {"r": run_id},
            )
        ).all()
    samples = []
    for question_id, metrics in rows:
        kind = kinds.get(question_id)
        if kind in {"answerable", "unanswerable"} and "error" not in metrics:
            samples.append((kind, metrics.get("best_similarity")))
    return samples
