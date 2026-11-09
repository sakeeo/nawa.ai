"""Renders docs/evaluation-report.md and small inline SVG bar charts. Pure and deterministic."""

from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

from nawa.evaluation.experiments import ArmResult, ExperimentResult, SweepRow

# metric -> (target, operator); ">=" higher is better, "<" lower is better.
TARGETS: dict[str, tuple[float, str]] = {
    "recall_at_5": (0.85, ">="),
    "mrr": (0.70, ">="),
    "faithfulness": (0.90, ">="),
    "citation_accuracy": (0.90, ">="),
    "correct_refusal_rate": (0.90, ">="),
    "injection_resistance": (1.0, ">="),
    "p95_ttft_ms": (3000.0, "<"),
}

ANALYSIS_PLACEHOLDER = "_Not written yet: add the analysis from the real numbers._"

LABELS = {
    "recall_at_5": "Recall@5",
    "mrr": "MRR",
    "faithfulness": "Faithfulness",
    "citation_accuracy": "Citation accuracy",
    "correct_refusal_rate": "Correct refusal rate",
    "injection_resistance": "Injection resistance",
    "p95_ttft_ms": "p95 time to first token",
    "p50_ttft_ms": "p50 time to first token",
    "p50_plan_ms": "p50 retrieval latency",
    "p95_plan_ms": "p95 retrieval latency",
}


def label(metric: str) -> str:
    return LABELS.get(metric, metric)


def fmt(metric: str, value: float) -> str:
    return f"{value:.0f} ms" if metric.endswith("_ms") else f"{value:.3f}"


def _delta(metric: str, value: float, target: float) -> str:
    diff = value - target
    return f"{diff:+.0f} ms" if metric.endswith("_ms") else f"{diff:+.3f}"


def _meets(value: float, target: float, op: str) -> bool:
    return value >= target if op == ">=" else value < target


def _cell(arm: ArmResult, metric: str) -> str:
    if arm.status != "ok":
        return "n/a"
    if metric not in arm.metrics:
        return "n/a"
    return fmt(metric, arm.metrics[metric])


def _table(experiment: ExperimentResult) -> list[str]:
    head = ["Arm", *[label(m) for m in experiment.metrics], "Status"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for arm in experiment.arms:
        cells = [f"`{arm.name}`", *[_cell(arm, m) for m in experiment.metrics]]
        status = "ok" if arm.status == "ok" else f"{arm.status}: {arm.reason}"
        lines.append("| " + " | ".join([*cells, status]) + " |")
    return lines


def reading(experiment: ExperimentResult) -> str:
    """A short factual sentence per metric: which arm led and by how much."""
    ran = [a for a in experiment.arms if a.status == "ok"]
    skipped = [a for a in experiment.arms if a.status != "ok"]
    parts: list[str] = []
    for metric in experiment.metrics:
        scored = [a for a in ran if metric in a.metrics]
        if len(scored) < 2:
            continue
        lower_better = metric.endswith("_ms")
        ordered = sorted(scored, key=lambda a: a.metrics[metric], reverse=not lower_better)
        best, runner_up = ordered[0], ordered[1]
        gap = abs(best.metrics[metric] - runner_up.metrics[metric])
        if gap == 0:
            parts.append(
                f"{label(metric)}: tie between `{best.name}` and `{runner_up.name}` "
                f"({fmt(metric, best.metrics[metric])})."
            )
        else:
            parts.append(
                f"{label(metric)}: `{best.name}` is {'lowest' if lower_better else 'highest'} at "
                f"{fmt(metric, best.metrics[metric])}, ahead of `{runner_up.name}` by "
                f"{fmt(metric, gap)}."
            )
    for arm in skipped:
        parts.append(f"`{arm.name}` did not produce results ({arm.status}: {arm.reason}).")
    return " ".join(parts) if parts else "No comparable results."


def bar_chart(title: str, metric: str, bars: Sequence[tuple[str, float]]) -> str:
    """A horizontal bar chart as a standalone SVG string (no external dependencies)."""
    width, row, left, right = 560, 28, 170, 90
    height = 40 + row * len(bars)
    peak = max((v for _, v in bars), default=0.0) or 1.0
    span = width - left - right
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}">',
        f'<text x="8" y="20" font-family="sans-serif" font-size="14" font-weight="bold">'
        f"{escape(title)}</text>",
    ]
    for i, (name, value) in enumerate(bars):
        y = 34 + i * row
        w = max(value / peak * span, 1.0)
        out.append(
            f'<text x="{left - 8}" y="{y + 15}" text-anchor="end" font-family="sans-serif" '
            f'font-size="12">{escape(name)}</text>'
            f'<rect x="{left}" y="{y}" width="{w:.1f}" height="18" fill="#3b6fb6"/>'
            f'<text x="{left + w + 6:.1f}" y="{y + 14}" font-family="sans-serif" font-size="12">'
            f"{escape(fmt(metric, value))}</text>"
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_charts(experiments: Sequence[ExperimentResult]) -> dict[str, str]:
    """`eval-<experiment>.svg` for every experiment with at least two scored arms."""
    charts: dict[str, str] = {}
    for exp in experiments:
        if not exp.metrics:
            continue
        metric = exp.metrics[0]
        bars = [
            (a.name, a.metrics[metric])
            for a in exp.arms
            if a.status == "ok" and metric in a.metrics
        ]
        if len(bars) >= 2:
            charts[f"eval-{exp.name}.svg"] = bar_chart(
                f"{exp.title}: {label(metric)}", metric, bars
            )
    return charts


def render(
    *,
    setup: Mapping[str, str],
    experiments: Sequence[ExperimentResult],
    sweep: Sequence[SweepRow],
    chosen: SweepRow | None,
    min_answerable_recall: float,
    final: ArmResult | None,
    limitations: Sequence[str],
    analysis: str = "",
    charts: Sequence[str] = (),
) -> str:
    """The full report. Same inputs always give the same text."""
    lines = ["# Evaluation report", "", "## Setup", "", "| Item | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in setup.items()]
    for exp in experiments:
        lines += ["", f"## Experiment: {exp.title}", ""]
        if exp.note:
            lines += [exp.note, ""]
        lines += _table(exp)
        lines += ["", reading(exp)]
        chart = f"eval-{exp.name}.svg"
        if chart in charts:
            lines += ["", f"![{exp.title}](images/{chart})"]

    lines += ["", "## Relevance threshold calibration", ""]
    lines += [
        "Replay of the relevance gate (answer when the best cosine similarity reaches the "
        "threshold) over the recorded answerable and unanswerable items.",
        "",
        "| Threshold | Refusal precision | Correct refusal rate | Answerable recall |",
        "|---|---|---|---|",
    ]
    for r in sweep:
        mark = " (chosen)" if chosen is not None and r.threshold == chosen.threshold else ""
        lines.append(
            f"| {r.threshold:.2f}{mark} | {r.refusal_precision:.3f} | "
            f"{r.correct_refusal_rate:.3f} | {r.answerable_recall:.3f} |"
        )
    if chosen is None:
        lines += [
            "",
            f"No threshold keeps answerable recall at or above {min_answerable_recall:.2f}.",
        ]
    else:
        lines += [
            "",
            f"Chosen `RAG_MIN_SIMILARITY` = {chosen.threshold:.2f}: highest correct refusal rate "
            f"({chosen.correct_refusal_rate:.3f}) with answerable recall at least "
            f"{min_answerable_recall:.2f} (got {chosen.answerable_recall:.3f}).",
        ]

    lines += ["", "## Targets versus results", ""]
    if final is None or final.status != "ok":
        reason = f" ({final.status}: {final.reason})" if final else ""
        lines.append(f"No complete run of the final configuration is available{reason}.")
    else:
        lines += [
            f"Configuration `{final.name}`.",
            "",
            "| Metric | Target | Result | Status |",
            "|---|---|---|---|",
        ]
        missed: list[str] = []
        for metric, (target, op) in TARGETS.items():
            if metric not in final.metrics:
                lines.append(
                    f"| {label(metric)} | {op} {fmt(metric, target)} | n/a | not measured |"
                )
                continue
            value = final.metrics[metric]
            if _meets(value, target, op):
                status = "met"
            else:
                status = f"missed ({_delta(metric, value, target)})"
                missed.append(label(metric))
            shown = fmt(metric, value)
            lines.append(f"| {label(metric)} | {op} {fmt(metric, target)} | {shown} | {status} |")
        lines += [""]
        lines.append(
            "Missed targets: " + ", ".join(missed) + ". Likely causes are in the analysis below."
            if missed
            else "All targets met."
        )

    lines += ["", "## Analysis", "", analysis.strip() or ANALYSIS_PLACEHOLDER]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in limitations]
    return "\n".join(lines) + "\n"


def extract_analysis(existing: str) -> str:
    """The body of an existing `## Analysis` section, so regenerating keeps hand-written text."""
    marker = "\n## Analysis\n"
    if marker not in existing:
        return ""
    body = existing.split(marker, 1)[1].split("\n## ", 1)[0].strip()
    return "" if body == ANALYSIS_PLACEHOLDER else body
