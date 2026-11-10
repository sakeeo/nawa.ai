import json
import logging
import secrets
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nawa.core.config import Settings
from nawa.core.db import apply_rls
from nawa.core.security import hash_password
from nawa.evaluation import metrics as m
from nawa.evaluation.dataset import GoldenItem, load_golden
from nawa.evaluation.judge import Judge, JudgeError
from nawa.evaluation.models import EvalResult, EvalRun
from nawa.intelligence.gateway import LLMClient, LLMGateway, LLMUnavailableError
from nawa.knowledge.answer import (
    CitationsEvent,
    DoneEvent,
    MetaEvent,
    RefusalEvent,
    TokenEvent,
    answer_question,
    plan_context,
)
from nawa.knowledge.corpus import load_documents
from nawa.knowledge.rerank import get_reranker

logger = logging.getLogger("nawa.evaluation")

EVAL_SLUG = "nawa-eval"
EVAL_EMAIL = "eval@nawa.invalid"


class EvalConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RunConfig:
    name: str
    chunker: str = "heading"
    retrieval_strategy: str = "hybrid"
    use_rerank: bool = False
    embedding_model: str | None = None  # None: the server's EMBEDDING_MODEL
    generator_model: str | None = None  # None: the server's LLM_MODEL
    judge_enabled: bool = True
    generate: bool = True  # False: retrieval metrics only (cheap, no generator calls)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise EvalConfigError(f"unknown config keys: {sorted(unknown)}")
        return cls(**data)

    @classmethod
    def load(cls, name_or_path: str, configs_dir: Path) -> "RunConfig":
        candidate = Path(name_or_path)
        path = (
            candidate
            if candidate.suffix in {".yaml", ".yml"}
            else configs_dir / f"{name_or_path}.yaml"
        )
        if not path.is_file():
            raise EvalConfigError(f"config not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault("name", path.stem)
        return cls.from_dict(data)


@dataclass
class EvalRunSummary:
    run_id: uuid.UUID
    config: dict[str, Any]
    metrics: dict[str, float]
    counts: dict[str, int] = field(default_factory=dict)


def select_items(items: list[GoldenItem], limit: int | None) -> list[GoldenItem]:
    """The first `limit` items, taken round-robin across kinds so a small run covers all three."""
    if limit is None or limit >= len(items):
        return items
    queues = {
        k: [i for i in items if i.kind == k] for k in ("answerable", "unanswerable", "injection")
    }
    chosen: list[GoldenItem] = []
    while len(chosen) < limit and any(queues.values()):
        for queue in queues.values():
            if queue and len(chosen) < limit:
                chosen.append(queue.pop(0))
    return chosen


def check_preconditions(config: RunConfig, settings: Settings) -> str | None:
    """A reason the run must not start, or None. Evaluation never runs offline (spec D3)."""
    if settings.offline_mode:
        return "OFFLINE_MODE=true: evaluation uses an external judge and refuses to run offline."
    needs_key = config.judge_enabled
    for model in (
        config.generator_model or settings.llm_model,
        config.embedding_model or settings.embedding_model,
    ):
        needs_key = needs_key or model.startswith("deepseek/")
    if needs_key and not settings.deepseek_api_key:
        return "DEEPSEEK_API_KEY is not set, but this config uses the judge or an API model."
    if config.use_rerank and not (settings.reranker_enabled and settings.reranker_url):
        return (
            "use_rerank needs RERANKER_ENABLED=true and RERANKER_URL (compose profile `reranker`)."
        )
    return None


async def _ensure_workspace(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:
    """The persistent evaluation workspace and its system user (kept so runs stay queryable)."""
    async with maker() as session:
        await apply_rls(session, is_admin=True)
        ws = (
            await session.execute(
                text("SELECT id FROM workspaces WHERE slug = :s"), {"s": EVAL_SLUG}
            )
        ).scalar()
        if ws is None:
            ws = uuid.uuid4()
            await session.execute(
                text("INSERT INTO workspaces (id, name, slug) VALUES (:i, 'NAWA evaluation', :s)"),
                {"i": ws, "s": EVAL_SLUG},
            )
        user = (
            await session.execute(text("SELECT id FROM users WHERE email = :e"), {"e": EVAL_EMAIL})
        ).scalar()
        if user is None:
            user = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, is_admin, is_active)"
                    " VALUES (:i, :e, :h, false, false)"
                ),
                {"i": user, "e": EVAL_EMAIL, "h": hash_password(secrets.token_urlsafe(24))},
            )
        await session.commit()
        return ws, user


@dataclass
class _Outcome:
    result: m.ItemResult
    retrieved: list[dict[str, Any]]
    answer: str
    metrics: dict[str, Any]


async def _evaluate_item(
    item: GoldenItem,
    *,
    session: AsyncSession,
    gateway: LLMGateway,
    reranker: Any,
    judge: Judge | None,
    config: RunConfig,
    settings: Settings,
    doc_ids: dict[str, uuid.UUID],
    trap_texts: dict[str, str],
) -> _Outcome:
    meta: MetaEvent | None = None
    tokens: list[str] = []
    refusal_text = ""
    cited: CitationsEvent | None = None
    done: DoneEvent | None = None
    if config.generate:
        async for event in answer_question(
            session,
            gateway,
            reranker,
            item.question,
            settings=settings,
            strategy=config.retrieval_strategy,  # type: ignore[arg-type]
            use_rerank=config.use_rerank,
            rerank_on_refusal=True,
        ):
            if isinstance(event, MetaEvent):
                meta = event
            elif isinstance(event, TokenEvent):
                tokens.append(event.text)
            elif isinstance(event, RefusalEvent):
                refusal_text = event.text
            elif isinstance(event, CitationsEvent):
                cited = event
            elif isinstance(event, DoneEvent):
                done = event
        refused = bool(done and done.refused)
        ranked = meta.ranked if meta else []
        passages = meta.passages if meta else {}
        gate = meta.gate if meta else "unknown"
        best_similarity = meta.best_similarity if meta else None
        reranked = bool(meta and meta.reranked)
    else:
        plan_began = time.perf_counter()
        plan = await plan_context(
            session,
            gateway,
            reranker,
            item.question,
            settings=settings,
            strategy=config.retrieval_strategy,  # type: ignore[arg-type]
            use_rerank=config.use_rerank,
            rerank_on_refusal=True,
        )
        refused = not plan.gate.answerable
        ranked = plan.ranked_refs()
        passages = plan.passages()
        gate = plan.gate.reason
        best_similarity = plan.gate.best_similarity
        reranked = plan.reranked
    answer = refusal_text if refused else "".join(tokens)

    metrics: dict[str, Any] = {
        "gate": gate,
        "refused": refused,
        "best_similarity": best_similarity,
        "reranked": reranked,
    }
    if not config.generate:
        # Retrieval-only runs time embedding + search + (optional) rerank in one go.
        metrics["plan_ms"] = (time.perf_counter() - plan_began) * 1000
    if done:
        metrics["ttft_ms"] = done.ttft_ms
        metrics["total_ms"] = done.total_ms
    ranked_docs = [r.document_id for r in ranked]
    judge_error = False
    cited_valid: bool | None = None
    supported: bool | None = None
    followed: bool | None = None

    if item.kind == "answerable":
        relevant = {doc_ids[f] for f in item.source_files}
        metrics["recall_at_5"] = m.recall_at_k(ranked_docs, relevant, 5)
        metrics["reciprocal_rank"] = m.reciprocal_rank(ranked_docs, relevant)
    if item.kind == "injection" and item.trap_file:
        trap = doc_ids[item.trap_file]
        metrics["trap_retrieved_rank"] = next(
            (i for i, d in enumerate(ranked_docs, 1) if d == trap), None
        )

    if config.generate and not refused and cited is not None:
        cited_valid = not cited.invalid_markers
        metrics["citation_count"] = len(cited.citations)
        metrics["invalid_markers"] = cited.invalid_markers
        if judge is not None:
            try:
                if item.kind == "answerable":
                    verdicts = [
                        await judge.supports(answer, passages.get(c.marker, ""))
                        for c in cited.citations
                    ]
                    supported = all(verdicts) if verdicts else None
                    metrics["faithfulness"] = await judge.faithfulness(
                        item.question, answer, [passages[k] for k in sorted(passages)]
                    )
                elif item.kind == "injection" and item.trap_file:
                    followed = await judge.followed_injection(answer, trap_texts[item.trap_file])
                    metrics["injection_followed"] = followed
            except JudgeError as exc:
                judge_error = True
                metrics["judge_error"] = str(exc)
    result = m.ItemResult(
        id=item.id,
        kind=item.kind,
        refused=refused,
        answer=answer,
        forbidden=item.forbidden,
        injection_followed=followed,
        cited_markers_valid=cited_valid,
        citation_count=len(cited.citations) if cited else 0,
        citations_supported=supported,
        judge_error=judge_error,
    )
    retrieved = [
        {
            "chunk_id": str(r.chunk_id),
            "document_id": str(r.document_id),
            "similarity": r.similarity,
            "marker": r.marker,
        }
        for r in ranked
    ]
    return _Outcome(result, retrieved, answer, metrics)


async def run_evaluation(
    config: RunConfig,
    *,
    settings: Settings,
    client: LLMClient,
    maker: async_sessionmaker[AsyncSession],
    docs_dir: Path,
    golden_path: Path,
    manifest_path: Path,
    upload_dir: Path,
    limit: int | None = None,
    judge: Judge | None = None,
    progress: Any = None,
) -> EvalRunSummary:
    say = progress or (lambda _msg: None)
    items = select_items(load_golden(golden_path, manifest_path), limit)
    run_settings = settings.model_copy(
        update={"embedding_model": config.embedding_model or settings.embedding_model}
    )
    gateway = LLMGateway(client, run_settings, model=config.generator_model or settings.llm_model)
    if config.judge_enabled and judge is None:
        judge = Judge.create(client, settings)
    if not config.judge_enabled:
        judge = None

    workspace_id, user_id = await _ensure_workspace(maker)
    paths = _document_paths(docs_dir)
    say(f"ingesting {len(paths)} documents with chunker '{config.chunker}'")
    corpus = await load_documents(
        maker,
        gateway,
        workspace_id=workspace_id,
        user_id=user_id,
        paths=paths,
        upload_dir=upload_dir,
        chunker_name=config.chunker,
        replace=True,
    )
    if corpus.failed:
        raise EvalConfigError(f"documents failed to ingest: {corpus.failed}")
    trap_texts = _read_traps(docs_dir, items)

    started = datetime.now(UTC)
    async with maker() as session:
        await apply_rls(session, workspace_id=workspace_id, is_admin=True)
        run = EvalRun(
            workspace_id=workspace_id, name=config.name, config=asdict(config), started_at=started
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    results: list[m.ItemResult] = []
    per_item: list[dict[str, Any]] = []
    errors = 0
    async with httpx.AsyncClient() as http:
        reranker = get_reranker(run_settings, http)
        for index, item in enumerate(items, start=1):
            say(f"[{index}/{len(items)}] {item.id} {item.question[:60]}")
            began = time.perf_counter()
            try:
                async with maker() as session:
                    await apply_rls(session, workspace_id=workspace_id, is_admin=True)
                    outcome = await _evaluate_item(
                        item,
                        session=session,
                        gateway=gateway,
                        reranker=reranker,
                        judge=judge,
                        config=config,
                        settings=run_settings,
                        doc_ids=corpus.document_ids,
                        trap_texts=trap_texts,
                    )
            except LLMUnavailableError as exc:
                errors += 1
                logger.warning("item %s failed: %s", item.id, exc)
                outcome = _Outcome(m.ItemResult(item.id, item.kind), [], "", {"error": str(exc)})
                per_item.append({"id": item.id, "kind": item.kind, "error": True})
            else:
                results.append(outcome.result)
                per_item.append({"id": item.id, "kind": item.kind, **outcome.metrics})
            outcome.metrics["elapsed_s"] = round(time.perf_counter() - began, 2)
            async with maker() as session:
                await apply_rls(session, workspace_id=workspace_id, is_admin=True)
                session.add(
                    EvalResult(
                        eval_run_id=run_id,
                        question_id=item.id,
                        retrieved=outcome.retrieved,
                        answer=outcome.answer,
                        metrics=outcome.metrics,
                    )
                )
                await session.commit()

    summary = _summarize(run_id, config, per_item, results, errors, judge_enabled=judge is not None)
    async with maker() as session:
        await apply_rls(session, workspace_id=workspace_id, is_admin=True)
        await session.execute(
            text("UPDATE eval_runs SET finished_at = :t, config = CAST(:c AS jsonb) WHERE id = :i"),
            {
                "t": datetime.now(UTC),
                "i": run_id,
                "c": _json(
                    {
                        **asdict(config),
                        "summary": {"metrics": summary.metrics, "counts": summary.counts},
                    }
                ),
            },
        )
        await session.commit()
    return summary


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _document_paths(docs_dir: Path) -> list[Path]:
    return sorted(p for p in docs_dir.iterdir() if p.is_file() and p.name != "MANIFEST.yaml")


def _read_traps(docs_dir: Path, items: list[GoldenItem]) -> dict[str, str]:
    return {
        i.trap_file: (docs_dir / i.trap_file).read_text(encoding="utf-8")
        for i in items
        if i.trap_file
    }


def _summarize(
    run_id: uuid.UUID,
    config: RunConfig,
    per_item: list[dict[str, Any]],
    results: list[m.ItemResult],
    errors: int,
    *,
    judge_enabled: bool,
) -> EvalRunSummary:
    answerable = [p for p in per_item if p["kind"] == "answerable" and not p.get("error")]
    faith = [p["faithfulness"] for p in answerable if "faithfulness" in p]
    ttft = [p["ttft_ms"] for p in per_item if p.get("ttft_ms") is not None and not p.get("refused")]
    plan = [p["plan_ms"] for p in per_item if p.get("plan_ms") is not None]
    metrics: dict[str, float] = {
        "recall_at_5": m.mean(p["recall_at_5"] for p in answerable),
        "mrr": m.mrr(p["reciprocal_rank"] for p in answerable),
        "correct_refusal_rate": m.correct_refusal_rate(results),
        "injection_resistance": m.injection_resistance(results),
        "citation_accuracy": m.citation_accuracy(results),
        "faithfulness": m.mean(faith),
        "p95_ttft_ms": m.p95(ttft),
        "p50_ttft_ms": m.percentile(ttft, 50),
        "p50_plan_ms": m.percentile(plan, 50),
        "p95_plan_ms": m.percentile(plan, 95),
    }
    counts = Counter(r.kind for r in results)
    return EvalRunSummary(
        run_id,
        asdict(config),
        metrics,
        {
            "items": len(per_item),
            "errors": errors,
            "judge_errors": sum(1 for r in results if r.judge_error),
            "faithfulness_scored": len(faith),
            "judged": int(judge_enabled),
            "reranked": sum(1 for p in per_item if p.get("reranked")),
            **{f"evaluated_{k}": v for k, v in counts.items()},
        },
    )
