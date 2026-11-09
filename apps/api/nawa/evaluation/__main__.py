import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nawa.core.config import get_settings
from nawa.evaluation.runner import (
    EvalConfigError,
    EvalRunSummary,
    RunConfig,
    check_preconditions,
    run_evaluation,
)
from nawa.intelligence.gateway import LiteLLMClient


def _repo_root() -> Path:
    """The checkout root (has an `evals` folder); inside the image it is overridden by env vars."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "evals").is_dir():
            return parent
    return Path.cwd()


TARGETS = {
    "recall_at_5": (0.85, ">="),
    "mrr": (0.70, ">="),
    "faithfulness": (0.90, ">="),
    "citation_accuracy": (0.90, ">="),
    "correct_refusal_rate": (0.90, ">="),
    "injection_resistance": (1.0, ">="),
    "p95_ttft_ms": (3000.0, "<"),
}


def format_summary(summary: EvalRunSummary) -> str:
    lines = [f"run {summary.run_id}  config {summary.config['name']}", ""]
    for key, (target, op) in TARGETS.items():
        value = summary.metrics.get(key, 0.0)
        ok = value >= target if op == ">=" else value < target
        shown = f"{value:.0f} ms" if key.endswith("_ms") else f"{value:.3f}"
        lines.append(
            f"  {key:22} {shown:>10}   target {op} {target:g}   {'ok' if ok else 'BELOW TARGET'}"
        )
    lines += ["", "  " + ", ".join(f"{k}={v}" for k, v in sorted(summary.counts.items()))]
    if summary.counts.get("errors") or summary.counts.get("judge_errors"):
        lines.append("  NOTE: items with errors are excluded from the averages above.")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    root = _repo_root()
    evals_dir = Path(os.environ.get("EVALS_DIR", root / "evals"))
    docs_dir = Path(os.environ.get("DEMO_DOCS_DIR", root / "seed" / "noesantara_docs"))
    try:
        config = RunConfig.load(args.config, evals_dir / "configs")
    except EvalConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    problem = check_preconditions(config, settings)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    engine = create_async_engine(settings.database_url)
    try:
        summary = await run_evaluation(
            config,
            settings=settings,
            client=LiteLLMClient(),
            maker=async_sessionmaker(engine, expire_on_commit=False),
            docs_dir=docs_dir,
            golden_path=evals_dir / "golden.yaml",
            manifest_path=docs_dir / "MANIFEST.yaml",
            upload_dir=Path(settings.upload_dir) / "eval",
            limit=args.limit,
            progress=lambda message: print(message, flush=True),
        )
    except EvalConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()
    print(format_summary(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nawa.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the golden dataset against one configuration")
    run.add_argument("--config", default="default", help="config name (evals/configs) or YAML path")
    run.add_argument("--limit", type=int, default=None, help="evaluate only N items (all kinds)")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
