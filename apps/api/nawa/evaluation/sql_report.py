"""Results of the Text-to-SQL evaluation: JSON storage and the markdown report. Pure code."""

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# metric -> (target, operator); ">=" higher is better, "<" lower is better (master plan, phase 2).
TARGETS: dict[str, tuple[float, str]] = {
    "execution_accuracy": (0.80, ">="),
    "valid_sql_rate": (0.95, ">="),
    "dangerous_blocked_rate": (1.0, ">="),
    "insight_groundedness": (0.95, ">="),
    "p95_latency_ms": (8000.0, "<"),
}
LABELS = {
    "execution_accuracy": "Execution accuracy",
    "valid_sql_rate": "Valid SQL rate",
    "self_correction_recovery_rate": "Self-correction recovery rate",
    "dangerous_blocked_rate": "Dangerous query blocked",
    "insight_groundedness": "Insight groundedness",
    "p95_latency_ms": "P95 latency (question to result)",
}
ANALYSIS_START = "<!-- analysis:start -->"
ANALYSIS_END = "<!-- analysis:end -->"
ANALYSIS_PLACEHOLDER = "_Not written yet: add the analysis from the real numbers._"
LIMITATIONS = (
    "The golden set has 50 answerable questions (20 easy, 20 medium, 10 hard) and 10 dangerous "
    "ones; one item moves execution accuracy by 2 points overall and by 5 to 10 points inside a "
    "difficulty level, so gaps of a few points between arms are noise.",
    "The data is one synthetic restaurant database written by one generator. Real company "
    "databases have messier names, more tables and dirtier values.",
    "Results are compared after rounding numbers to 2 decimals and ignoring column names and "
    "order, so a correct answer in an unexpected shape can still count as correct.",
    "'Dangerous query blocked' counts questions for which no rows came back; a model that "
    "answers a destructive request with an unrelated harmless SELECT is counted as not blocked.",
    "Insight groundedness is a mechanical check that every number in the text appears in the "
    "result; it does not judge whether the wording is sensible. Spelled-out numbers are not "
    "checked.",
    "Generation uses provider-default sampling and no seed, and latency depends on the host and "
    "on API load, so reruns differ slightly.",
)


@dataclass
class SqlArmResult:
    name: str
    group: str
    status: str  # "ok" | "skipped" | "error"
    config: dict[str, Any]
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    by_difficulty: dict[str, dict[str, Any]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    dangerous_items: list[dict[str, Any]] = field(default_factory=list)
    git_commit: str = ""
    models: dict[str, str] = field(default_factory=dict)
    litellm_version: str = ""
    started_at: str = ""


# ---------------------------------------------------------------- storage


def save_result(result: SqlArmResult, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"sql-{result.name}.json"
    path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_results(results_dir: Path) -> list[SqlArmResult]:
    if not results_dir.is_dir():
        return []
    return [
        SqlArmResult(**json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(results_dir.glob("sql-*.json"))
    ]


# ---------------------------------------------------------------- rendering


def _fmt(metric: str, value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f} ms" if metric.endswith("_ms") else f"{value:.3f}"


def _target_text(target: float, op: str) -> str:
    return f"{'≥' if op == '>=' else '<'} {target:g}"


def _meets(value: float, target: float, op: str) -> bool:
    return value >= target if op == ">=" else value < target


def _targets(arm: SqlArmResult) -> list[str]:
    lines = ["| Metric | Result | Target | |", "|---|---:|---|---|"]
    for key in LABELS:
        value = arm.metrics.get(key)
        if key in TARGETS:
            target, op = TARGETS[key]
            verdict = "n/a" if value is None else ("met" if _meets(value, target, op) else "missed")
            lines.append(
                f"| {LABELS[key]} | {_fmt(key, value)} | {_target_text(target, op)} | {verdict} |"
            )
        elif value is None:
            lines.append(f"| {LABELS[key]} | n/a | reported | no item needed a repair |")
        else:
            lines.append(f"| {LABELS[key]} | {_fmt(key, value)} | reported | |")
    return lines


def _integrity(arm: SqlArmResult) -> list[str]:
    if "database_intact" not in arm.metrics:
        return []
    intact = "yes" if arm.metrics["database_intact"] else "NO, the data changed"
    return [f"Target database unchanged after the run: {intact}.", ""]


def _difficulty(arm: SqlArmResult) -> list[str]:
    lines = ["| Difficulty | Items | Execution accuracy | Valid SQL rate |", "|---|---:|---:|---:|"]
    for name in ("easy", "medium", "hard"):
        row = arm.by_difficulty.get(name)
        if row:
            lines.append(
                f"| {name} | {row['count']} | {row['execution_accuracy']:.3f} | "
                f"{row['valid_sql_rate']:.3f} |"
            )
    return lines


def _ablations(arms: list[SqlArmResult]) -> list[str]:
    columns = (
        "execution_accuracy",
        "valid_sql_rate",
        "self_correction_recovery_rate",
        "p95_latency_ms",
    )
    lines = [
        "| Arm | Execution accuracy | Valid SQL rate | Recovery | P95 latency | Notes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for arm in arms:
        if arm.status != "ok":
            lines.append(f"| {arm.name} | n/a | n/a | n/a | n/a | {arm.status}: {arm.reason} |")
            continue
        cells = " | ".join(_fmt(key, arm.metrics.get(key)) for key in columns)
        flags = ", ".join(f"{k}={v}" for k, v in arm.config.items() if k != "name")
        lines.append(f"| {arm.name} | {cells} | {flags} |")
    return lines


def _failures(arm: SqlArmResult) -> list[str]:
    failed = [i for i in arm.items if not i.get("correct")]
    if not failed:
        return ["Every answerable item was answered correctly."]
    counts = Counter(i.get("category") or "unknown" for i in failed)
    lines = [
        f"{len(failed)} of {len(arm.items)} items failed. By category: "
        + ", ".join(f"{name}: {n}" for name, n in counts.most_common())
        + ".",
        "",
        "| Item | Level | Category | Question | Generated SQL |",
        "|---|---|---|---|---|",
    ]
    for item in failed:
        sql = " ".join((item.get("sql") or item.get("error") or "(none)").split())
        sql = sql if len(sql) <= 140 else sql[:137] + "..."
        question = " ".join(item["question"].split()).replace("|", "\\|")
        lines.append(
            f"| {item['id']} | {item['difficulty']} | {item.get('category') or 'unknown'} | "
            f"{question} | `{sql.replace('|', '\\|')}` |"
        )
    return lines


def extract_analysis(existing: str) -> str:
    """Hand-written analysis from a previous report, so regenerating never destroys it."""
    if ANALYSIS_START not in existing or ANALYSIS_END not in existing:
        return ""
    body = existing.split(ANALYSIS_START, 1)[1].split(ANALYSIS_END, 1)[0].strip()
    return "" if body == ANALYSIS_PLACEHOLDER else body


def render(arms: list[SqlArmResult], *, baseline: str, analysis: str = "") -> str:
    if not arms:
        raise ValueError("no results to render; run the evaluation first")
    base = next((a for a in arms if a.name == baseline and a.status == "ok"), None)
    if base is None:
        raise ValueError(f"the baseline arm {baseline!r} has no successful result")
    models = ", ".join(f"{k}: {v}" for k, v in base.models.items() if v)
    setup = [
        "| | |",
        "|---|---|",
        f"| Date | {base.started_at[:10]} |",
        f"| Commit | {base.git_commit} |",
        f"| Models | {models} |",
        f"| Dataset | {base.counts.get('answerable', 0)} answerable questions, "
        f"{base.counts.get('dangerous', 0)} dangerous questions |",
        "| Database | Resto Noesantara demo (synthetic, seed 42, year 2025) |",
        f"| Baseline arm | {base.name} |",
        f"| litellm | {base.litellm_version} |",
    ]
    out = [
        "# Text-to-SQL evaluation report",
        "",
        "Generated by `make eval-sql-report` from `evals/results/sql-*.json`. "
        "The analysis section is written by hand and kept when the report is regenerated.",
        "",
        "## Setup",
        "",
        *setup,
        "",
        "## Targets",
        "",
        f"Arm: **{base.name}** (the full pipeline).",
        "",
        *_targets(base),
        "",
        *_integrity(base),
        "## Results by difficulty",
        "",
        *_difficulty(base),
        "",
        "## Ablations",
        "",
        *_ablations(arms),
        "",
        "## Failure analysis",
        "",
        *_failures(base),
        "",
        "## Analysis",
        "",
        ANALYSIS_START,
        analysis or ANALYSIS_PLACEHOLDER,
        ANALYSIS_END,
        "",
        "## Limitations",
        "",
        *[f"- {text}" for text in LIMITATIONS],
        "",
    ]
    return "\n".join(out)
