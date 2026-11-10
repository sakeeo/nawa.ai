"""Runs the Text-to-SQL golden dataset through the production pipeline (decision P16).

Every question goes through `nawa.data.service.ask_question`, so the guard, the self-correction
and the read-only executor are exercised as they are in production. Dangerous questions are
never shortcut to the guard alone.
"""

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.config import Settings
from nawa.core.db import apply_rls
from nawa.data.connector import ConnectionParams, open_engine
from nawa.data.discovery import discover_schema
from nawa.data.executor import QueryResult, execute_readonly
from nawa.data.guard import check_sql, mark_checked
from nawa.data.insight import generate_insight
from nawa.data.semantic import SemanticModel, allowlist
from nawa.data.service import MAX_RETRIES, AskContext, AskOutcome, ask_question
from nawa.evaluation.runner import EvalConfigError, _ensure_workspace
from nawa.evaluation.sql_dataset import DangerItem, SqlItem, load_sql_golden
from nawa.evaluation.sql_metrics import (
    DIFFICULTIES,
    SqlItemResult,
    categorize_failure,
    results_equal,
    summarize,
)
from nawa.evaluation.sql_report import SqlArmResult
from nawa.intelligence.gateway import LLMClient, LLMGateway, TraceInfo
from nawa.intelligence.prompts import PromptRegistry

REFERENCE_TIMEOUT_S = 30
INTEGRITY_TABLES = ("orders", "order_items", "customers", "menu_items", "outlets")


@dataclass(frozen=True)
class SqlRunConfig:
    name: str
    generator_model: str | None = None  # None: the server's LLM_MODEL
    schema_linking: bool = True
    self_correction: bool = True
    fewshot: bool = False
    insight: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SqlRunConfig":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise EvalConfigError(f"unknown config keys: {sorted(unknown)}")
        return cls(**data)


@dataclass(frozen=True)
class SqlArm:
    config: SqlRunConfig
    group: str
    requires_env: tuple[str, ...] = ()


@dataclass(frozen=True)
class SqlExperiments:
    baseline: str
    arms: tuple[SqlArm, ...] = field(default_factory=tuple)


def load_sql_arms(path: Path) -> SqlExperiments:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    arms = tuple(
        SqlArm(
            config=SqlRunConfig.from_dict(row["config"]),
            group=str(row.get("group", "ablation")),
            requires_env=tuple(row.get("requires_env", ())),
        )
        for row in raw.get("arms", [])
    )
    names = [a.config.name for a in arms]
    if len(names) != len(set(names)):
        raise EvalConfigError("duplicate arm names in the SQL experiments file")
    baseline = str(raw.get("baseline", ""))
    if baseline not in names:
        raise EvalConfigError(f"the baseline arm {baseline!r} is not defined")
    return SqlExperiments(baseline=baseline, arms=arms)


def sql_target(settings: Settings) -> ConnectionParams:
    """Where the demo database lives: the server of the platform database, read-only role."""
    base = make_url(settings.database_owner_url or settings.database_url)
    return ConnectionParams(
        host=base.host or "127.0.0.1",
        port=base.port or 5432,
        database=settings.demo_database_name,
        username=settings.demo_db_readonly_user,
        password=settings.demo_db_readonly_password or "",
        ssl_mode="prefer",
    )


def check_sql_preconditions(config: SqlRunConfig, settings: Settings) -> str | None:
    """A reason the run must not start, or None. Evaluation never runs offline (spec D3)."""
    if settings.offline_mode:
        return "OFFLINE_MODE=true: evaluation uses an external provider and refuses to run offline."
    if config.fewshot:
        return "Few-shot examples need approved queries, which are not built yet (task T2-15)."
    if not settings.demo_db_readonly_password:
        return (
            "DEMO_DB_READONLY_PASSWORD is not set: the demo database has no read-only role to use."
        )
    if (config.generator_model or settings.llm_model).startswith("deepseek/") and not (
        settings.deepseek_api_key
    ):
        return "DEEPSEEK_API_KEY is not set, but this config uses a DeepSeek model."
    return None


def select_sql_items(
    items: list[SqlItem], dangerous: list[DangerItem], limit: int | None
) -> tuple[list[SqlItem], list[DangerItem]]:
    """The first `limit` items, round-robin across difficulties; dangerous ones are cut to match."""
    if limit is None or limit >= len(items):
        return items, dangerous if limit is None else dangerous[:limit]
    queues = {d: [i for i in items if i.difficulty == d] for d in DIFFICULTIES}
    chosen: list[SqlItem] = []
    while len(chosen) < limit and any(queues.values()):
        for queue in queues.values():
            if queue and len(chosen) < limit:
                chosen.append(queue.pop(0))
    return chosen, dangerous[:limit]


async def _run_reference(
    target: ConnectionParams, sql: str, allow: dict[str, set[str]], settings: Settings
) -> QueryResult:
    verdict = check_sql(sql, allow, max_rows=settings.data_max_rows)
    return await execute_readonly(
        target,
        mark_checked(verdict),
        timeout_s=REFERENCE_TIMEOUT_S,
        max_rows=settings.data_max_rows,
    )


async def _integrity(
    target: ConnectionParams, allow: dict[str, set[str]], settings: Settings
) -> Any:
    # Table names come from the constant above, never from input.
    counts = ", ".join(f"(SELECT count(*) FROM {table})" for table in INTEGRITY_TABLES)  # noqa: S608
    result = await _run_reference(target, f"SELECT {counts}", allow, settings)
    return result.rows


async def run_sql_eval(
    config: SqlRunConfig,
    *,
    settings: Settings,
    client: LLMClient,
    maker: async_sessionmaker[AsyncSession],
    target: ConnectionParams,
    model: SemanticModel,
    golden_path: Path,
    limit: int | None = None,
    progress: Any = None,
) -> SqlArmResult:
    say = progress or (lambda _message: None)
    allow = allowlist(model)
    all_items, all_dangerous = load_sql_golden(
        golden_path, allow=allow, enforce_counts=limit is None
    )
    items, dangerous = select_sql_items(all_items, all_dangerous, limit)
    started_at = datetime.now(UTC).isoformat()

    async with open_engine(target) as engine:
        schema = await discover_schema(engine, sample_allow=allow)
    workspace_id, user_id = await _ensure_workspace(maker)
    gateway = LLMGateway(client, settings, model=config.generator_model or settings.llm_model)
    registry = PromptRegistry()
    model_key = (uuid.uuid4(), 1)
    retries = MAX_RETRIES if config.self_correction else 0

    say(f"computing the expected result of {len(items)} reference queries")
    expected = {
        item.id: await _run_reference(target, item.reference_sql, allow, settings) for item in items
    }
    integrity_before = await _integrity(target, allow, settings)

    async def ask(question: str) -> tuple[AskOutcome | None, float, str | None]:
        async with maker() as session:
            await apply_rls(session, workspace_id=workspace_id, user_id=user_id)
            context = AskContext(
                session=session,
                workspace_id=workspace_id,
                user_id=user_id,
                data_source_id=None,
                params=target,
                model=model,
                model_key=model_key,
                schema=schema,
                gateway=gateway,
                registry=registry,
                settings=settings,
                max_retries=retries,
                schema_linking=config.schema_linking,
            )
            began = time.perf_counter()
            try:
                outcome = await ask_question(context, question)
                await session.commit()
            except Exception as exc:  # one failing item must not end the run
                elapsed = (time.perf_counter() - began) * 1000
                return None, elapsed, f"{type(exc).__name__}: {exc}"[:300]
            return outcome, (time.perf_counter() - began) * 1000, None

    results: list[SqlItemResult] = []
    rows: list[dict[str, Any]] = []
    insight_ms: list[float] = []
    for number, item in enumerate(items, start=1):
        say(f"[{number}/{len(items)}] {item.id}")
        outcome, elapsed, crash = await ask(item.question)
        status = outcome.status if outcome else "error"
        actual = outcome.result if outcome else None
        correct = bool(
            outcome
            and status == "ok"
            and actual is not None
            and results_equal(actual, expected[item.id], ordered=item.ordered)
        )
        grounded: bool | None = None
        if config.insight and outcome and status == "ok" and actual and actual.row_count > 0:
            began = time.perf_counter()
            try:
                narrative = await generate_insight(
                    gateway,
                    registry,
                    question=item.question,
                    columns=actual.columns,
                    rows=actual.rows,
                    trace=TraceInfo(name="eval.sql.insight", workspace_id=str(workspace_id)),
                )
                grounded = narrative.grounded and not narrative.used_fallback
                insight_ms.append((time.perf_counter() - began) * 1000)
            except Exception:  # the insight is optional; the metric skips this item
                grounded = None
        result = SqlItemResult(
            id=item.id,
            difficulty=item.difficulty,
            question=item.question,
            status=status,
            sql=outcome.sql if outcome else None,
            attempts=outcome.attempts if outcome else 0,
            correct=correct,
            latency_ms=elapsed,
            error=(outcome.error or outcome.blocked_reason) if outcome else crash,
            insight_grounded=grounded,
            tags=item.tags,
        )
        results.append(result)
        row = asdict(result)
        row["tags"] = list(item.tags)
        row["category"] = None if correct else categorize_failure(result, actual, expected[item.id])
        rows.append(row)

    dangerous_rows: list[dict[str, Any]] = []
    for number, danger in enumerate(dangerous, start=1):
        say(f"[danger {number}/{len(dangerous)}] {danger.id}")
        outcome, _, crash = await ask(danger.question)
        returned_rows = bool(outcome and outcome.result is not None)
        dangerous_rows.append(
            {
                "id": danger.id,
                "kind": danger.kind,
                "question": danger.question,
                "status": outcome.status if outcome else "error",
                "blocked": not returned_rows,
                "reason": (outcome.blocked_reason or outcome.error or outcome.clarification)
                if outcome
                else crash,
                "sql": outcome.sql if outcome else None,
            }
        )
    integrity_after = await _integrity(target, allow, settings)

    summary = summarize(
        results, dangerous=[bool(d["blocked"]) for d in dangerous_rows], insight_ms=insight_ms
    )
    summary["metrics"]["database_intact"] = integrity_before == integrity_after
    return SqlArmResult(
        name=config.name,
        group="",
        status="ok",
        config=asdict(config),
        metrics=summary["metrics"],
        by_difficulty=summary["by_difficulty"],
        counts=summary["counts"],
        items=rows,
        dangerous_items=dangerous_rows,
        models={
            "generator": config.generator_model or settings.llm_model,
            "embedding": settings.embedding_model,
        },
        started_at=started_at,
    )


def with_run_details(result: SqlArmResult, **details: Any) -> SqlArmResult:
    """A copy with fields only the caller knows (group, commit, litellm version)."""
    return replace(result, **details)
