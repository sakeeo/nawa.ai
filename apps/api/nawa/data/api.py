import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError

from nawa.core.audit import record_audit
from nawa.core.config import Settings
from nawa.core.crypto import get_vault
from nawa.core.errors import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)
from nawa.core.ratelimit import RateLimiter, get_redis
from nawa.data import fewshot, repository
from nawa.data.anomaly import detect_anomalies
from nawa.data.charts import choose_chart
from nawa.data.connector import ConnectionParams, open_engine, scrub, test_connection
from nawa.data.discovery import discover_schema
from nawa.data.executor import QueryExecutionError, execute_readonly
from nawa.data.guard import check_sql, mark_checked
from nawa.data.insight import generate_insight
from nawa.data.models import DataSource, QueryLog
from nawa.data.schemas import (
    AnomalyRead,
    AskRequest,
    AskResponse,
    ChartRead,
    ConnectionReportRead,
    DataSourceCreate,
    DataSourceCreated,
    DataSourceRead,
    DiscoveryRead,
    InsightRead,
    QueryFeedbackWrite,
    QueryLogRead,
    SemanticDraftRead,
    SemanticModelRead,
    SemanticModelWrite,
)
from nawa.data.semantic import (
    SemanticError,
    SemanticModel,
    allowlist,
    draft_from_schema,
    parse_semantic_yaml,
    to_yaml,
    validate_against_schema,
)
from nawa.data.service import AskContext, ask_question
from nawa.intelligence.deps import get_llm_client, model_for_provider
from nawa.intelligence.gateway import LLMClient, LLMGateway, TraceInfo
from nawa.intelligence.prompts import PromptRegistry
from nawa.workspace import repository as workspace_repository
from nawa.workspace.deps import (
    ManagerCtx,
    MemberCtx,
    SettingsDep,
    ViewerCtx,
    WorkspaceContext,
    require_csrf,
)

logger = logging.getLogger("nawa.data.api")

router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}",
    tags=["data"],
    dependencies=[Depends(require_csrf)],
)

SEES_ALL_QUERIES = ("manager", "admin")


async def _source(ctx: WorkspaceContext, source_id: uuid.UUID) -> DataSource:
    source = await repository.get_source(ctx.session, ctx.workspace_id, source_id)
    if source is None:
        raise NotFoundError("Data source not found")
    return source


async def _active_model(
    ctx: WorkspaceContext, source_id: uuid.UUID
) -> tuple[SemanticModel, uuid.UUID, int] | None:
    row = await repository.get_active_model(ctx.session, ctx.workspace_id, source_id)
    if row is None:
        return None
    return parse_semantic_yaml(row.yaml), row.id, row.version


async def _limit(redis: Redis, settings: Settings, kind: str, user_id: uuid.UUID) -> None:
    limiter = RateLimiter(redis, window_seconds=60)
    key = f"data-{kind}:{user_id}"
    if await limiter.is_blocked(key, settings.data_ask_limit_per_minute):
        raise RateLimitedError("Too many data questions. Try again in a minute.")
    await limiter.hit(key)


async def _gateway(ctx: WorkspaceContext, settings: Settings, client: LLMClient) -> LLMGateway:
    instance = await workspace_repository.get_instance_settings(ctx.session)
    if not instance.setup_completed or instance.ai_provider is None:
        raise ConflictError("Setup has not been completed")
    return LLMGateway(client, settings, model=model_for_provider(settings, instance.ai_provider))


# ---------------------------------------------------------------- data sources


@router.post("/data-sources", response_model=DataSourceCreated, status_code=201)
async def create_data_source(
    body: DataSourceCreate, ctx: ManagerCtx, settings: SettingsDep
) -> DataSourceCreated:
    vault = get_vault(settings)
    password = body.password.get_secret_value()
    try:
        source = await repository.create_source(
            ctx.session,
            vault,  # raises 503 without DATA_ENCRYPTION_KEY, before anything is stored
            workspace_id=ctx.workspace_id,
            created_by=ctx.user.id,
            name=body.name,
            host=body.host,
            port=body.port,
            database=body.database,
            username=body.username,
            password=password,
            ssl_mode=body.ssl_mode,
        )
    except IntegrityError as exc:
        await ctx.session.rollback()
        raise ConflictError("A data source with this name already exists") from exc
    report = await test_connection(
        ConnectionParams(
            body.host, body.port, body.database, body.username, password, body.ssl_mode
        )
    )
    await repository.set_source_status(
        ctx.session, source, ok=report.ok, error="; ".join(report.problems) or None
    )
    await record_audit(
        ctx.session,
        action="data_source.create",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=f"{source.id} {body.host}:{body.port}/{body.database}",
    )
    await ctx.session.commit()
    return DataSourceCreated(
        source=DataSourceRead.model_validate(source),
        report=ConnectionReportRead(
            ok=report.ok, server_version=report.server_version, problems=report.problems
        ),
    )


@router.get("/data-sources", response_model=list[DataSourceRead])
async def list_data_sources(ctx: ViewerCtx) -> list[DataSourceRead]:
    sources = await repository.list_sources(ctx.session, ctx.workspace_id)
    return [DataSourceRead.model_validate(s) for s in sources]


@router.post("/data-sources/{source_id}/test", response_model=ConnectionReportRead)
async def retest_data_source(
    source_id: uuid.UUID, ctx: ManagerCtx, settings: SettingsDep
) -> ConnectionReportRead:
    source = await _source(ctx, source_id)
    params = repository.params_for(source, get_vault(settings))
    active = await _active_model(ctx, source_id)
    tables = sorted(allowlist(active[0])) if active else None
    report = await test_connection(params, tables=tables)
    await repository.set_source_status(
        ctx.session, source, ok=report.ok, error="; ".join(report.problems) or None
    )
    await ctx.session.commit()
    return ConnectionReportRead(
        ok=report.ok, server_version=report.server_version, problems=report.problems
    )


@router.post("/data-sources/{source_id}/discover", response_model=DiscoveryRead)
async def discover_data_source(
    source_id: uuid.UUID, ctx: ManagerCtx, settings: SettingsDep
) -> DiscoveryRead:
    source = await _source(ctx, source_id)
    params = repository.params_for(source, get_vault(settings))
    active = await _active_model(ctx, source_id)
    # Sample values only where the semantic model allows it; without a model, nowhere.
    sample_allow = allowlist(active[0]) if active else {}
    try:
        async with open_engine(params) as engine:
            tables = await discover_schema(engine, sample_allow=sample_allow)
    except Exception as exc:
        detail = scrub(f"{type(exc).__name__}: {exc}", params.password)[:200]
        raise QueryExecutionError(f"Cannot read the schema of the data source: {detail}") from exc
    snapshot = await repository.save_snapshot(ctx.session, ctx.workspace_id, source_id, tables)
    created_at = snapshot.created_at
    await ctx.session.commit()
    return DiscoveryRead(
        tables=len(tables),
        columns=sum(len(t.columns) for t in tables),
        sampled_columns=sum(1 for t in tables for c in t.columns if c.samples),
        has_semantic_model=active is not None,
        created_at=created_at,
    )


@router.delete("/data-sources/{source_id}", status_code=204)
async def delete_data_source(source_id: uuid.UUID, ctx: ManagerCtx) -> Response:
    if not await repository.delete_source(ctx.session, ctx.workspace_id, source_id):
        raise NotFoundError("Data source not found")
    await record_audit(
        ctx.session,
        action="data_source.delete",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=str(source_id),
    )
    await ctx.session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- semantic model


@router.get("/data-sources/{source_id}/semantic-model", response_model=SemanticModelRead)
async def get_semantic_model(source_id: uuid.UUID, ctx: ViewerCtx) -> SemanticModelRead:
    await _source(ctx, source_id)
    row = await repository.get_active_model(ctx.session, ctx.workspace_id, source_id)
    if row is None:
        raise NotFoundError("No semantic model is active for this data source")
    return SemanticModelRead(version=row.version, yaml=row.yaml, created_at=row.created_at)


@router.post("/data-sources/{source_id}/semantic-model/draft", response_model=SemanticDraftRead)
async def draft_semantic_model(source_id: uuid.UUID, ctx: ManagerCtx) -> SemanticDraftRead:
    await _source(ctx, source_id)
    schema = await repository.latest_snapshot(ctx.session, ctx.workspace_id, source_id)
    if schema is None:
        raise ConflictError("Run schema discovery first")
    return SemanticDraftRead(yaml=to_yaml(draft_from_schema(schema)))


@router.put("/data-sources/{source_id}/semantic-model", response_model=SemanticModelRead)
async def save_semantic_model(
    source_id: uuid.UUID, body: SemanticModelWrite, ctx: ManagerCtx
) -> SemanticModelRead:
    await _source(ctx, source_id)
    schema = await repository.latest_snapshot(ctx.session, ctx.workspace_id, source_id)
    if schema is None:
        raise ConflictError("Run schema discovery first")
    try:
        model = parse_semantic_yaml(body.yaml)
    except SemanticError as exc:
        raise ValidationFailedError(
            "The semantic model is not valid", extra={"problems": exc.problems}
        ) from exc
    problems = validate_against_schema(model, schema)
    if problems:
        raise ValidationFailedError(
            "The semantic model does not match the data source", extra={"problems": problems}
        )
    row = await repository.save_semantic_model(
        ctx.session,
        workspace_id=ctx.workspace_id,
        source_id=source_id,
        yaml_text=body.yaml,
        created_by=ctx.user.id,
    )
    version, created_at = row.version, row.created_at
    await record_audit(
        ctx.session,
        action="semantic_model.activate",
        actor_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        target=f"{source_id} v{version}",
    )
    await ctx.session.commit()
    return SemanticModelRead(version=version, yaml=body.yaml, created_at=created_at)


# ---------------------------------------------------------------- ask


@router.post("/data/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    ctx: MemberCtx,
    settings: SettingsDep,
    client: Annotated[LLMClient, Depends(get_llm_client)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> AskResponse:
    await _limit(redis, settings, "ask", ctx.user.id)
    gateway = await _gateway(ctx, settings, client)
    source = await _source(ctx, body.data_source_id)
    if source.status != "ok":
        raise ConflictError("The data source has not passed its connection test")
    active = await _active_model(ctx, source.id)
    if active is None:
        raise ConflictError("No semantic model is active for this data source")
    schema = await repository.latest_snapshot(ctx.session, ctx.workspace_id, source.id)
    if schema is None:
        raise ConflictError("Run schema discovery first")
    model, model_id, version = active
    examples: list[tuple[str, str]] = []
    try:  # best effort: no example is better than a failed question
        examples = await fewshot.similar_examples(
            ctx.session,
            gateway,
            workspace_id=ctx.workspace_id,
            source_id=source.id,
            question=body.question,
        )
    except Exception:
        logger.warning("Looking up few-shot examples failed", exc_info=True)
    outcome = await ask_question(
        AskContext(
            session=ctx.session,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user.id,
            data_source_id=source.id,
            params=repository.params_for(source, get_vault(settings)),
            model=model,
            model_key=(model_id, version),
            schema=schema,
            gateway=gateway,
            registry=PromptRegistry(),
            settings=settings,
            fewshot=examples,
        ),
        body.question,
    )
    await ctx.session.commit()  # keeps the audit row of a blocked or failed question too
    result = outcome.result
    columns = result.columns if result else []
    rows = result.rows if result else []
    chart = choose_chart(columns, rows) if result else None
    anomalies = detect_anomalies(columns, rows) if result else []
    return AskResponse(
        query_id=outcome.query_id,
        status=outcome.status,
        sql=outcome.sql,
        assumptions=outcome.assumptions,
        clarification=outcome.clarification,
        blocked_reason=outcome.blocked_reason,
        error=outcome.error,
        columns=columns,
        rows=rows,
        row_count=result.row_count if result else 0,
        truncated=result.truncated if result else False,
        duration_ms=result.duration_ms if result else 0,
        chart=ChartRead(kind=chart.kind, x=chart.x, y=chart.y, title=chart.title)
        if chart
        else None,
        attempts=outcome.attempts,
        linked_tables=outcome.linked_tables,
        anomalies=[
            AnomalyRead(label=a.label, value=a.value, z=a.z, direction=a.direction)
            for a in anomalies
        ],
    )


async def _own_or_managed_query(ctx: WorkspaceContext, query_id: uuid.UUID, *, owner_only: bool):  # type: ignore[no-untyped-def]
    entry = await repository.get_query(ctx.session, ctx.workspace_id, query_id)
    allowed = entry is not None and (
        entry.user_id == ctx.user.id or (not owner_only and ctx.role in SEES_ALL_QUERIES)
    )
    if entry is None or not allowed:
        raise NotFoundError("Query not found")
    return entry


@router.post("/data/queries/{query_id}/insight", response_model=InsightRead)
async def query_insight(
    query_id: uuid.UUID,
    ctx: MemberCtx,
    settings: SettingsDep,
    client: Annotated[LLMClient, Depends(get_llm_client)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> InsightRead:
    entry = await _own_or_managed_query(ctx, query_id, owner_only=False)
    if entry.status != "ok" or not entry.sql:
        raise ConflictError("Only a successful query has an insight")
    if entry.insight is not None:
        return InsightRead(text=entry.insight, grounded=bool(entry.insight_grounded), cached=True)
    await _limit(redis, settings, "insight", ctx.user.id)
    gateway = await _gateway(ctx, settings, client)
    if entry.data_source_id is None:
        raise ConflictError("The data source of this query was removed")
    source = await _source(ctx, entry.data_source_id)
    active = await _active_model(ctx, source.id)
    if active is None:
        raise ConflictError("No semantic model is active for this data source")
    # The rows are fetched again from the stored, guarded SQL; nothing comes from the client.
    verdict = check_sql(entry.sql, allowlist(active[0]), max_rows=settings.data_max_rows)
    if not verdict.ok:
        raise ConflictError("This query is no longer allowed by the semantic model")
    result = await execute_readonly(
        repository.params_for(source, get_vault(settings)),
        mark_checked(verdict),
        timeout_s=settings.data_query_timeout_s,
        max_rows=settings.data_max_rows,
    )
    insight = await generate_insight(
        gateway,
        PromptRegistry(),
        question=entry.question,
        columns=result.columns,
        rows=result.rows,
        trace=TraceInfo(
            name="data.insight",
            user_id=str(ctx.user.id),
            workspace_id=str(ctx.workspace_id),
        ),
    )
    await repository.update_query_insight(
        ctx.session, ctx.workspace_id, query_id, insight=insight.text, grounded=insight.grounded
    )
    await ctx.session.commit()
    return InsightRead(text=insight.text, grounded=insight.grounded, cached=False)


@router.get("/data/queries", response_model=list[QueryLogRead])
async def list_queries(
    ctx: MemberCtx, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[QueryLogRead]:
    own_only = None if ctx.role in SEES_ALL_QUERIES else ctx.user.id
    rows = await repository.list_queries(
        ctx.session, ctx.workspace_id, user_id=own_only, limit=limit
    )
    return [QueryLogRead.model_validate(r) for r in rows]


@router.post("/data/queries/{query_id}/feedback", status_code=204)
async def query_feedback(
    query_id: uuid.UUID,
    body: QueryFeedbackWrite,
    ctx: MemberCtx,
    settings: SettingsDep,
    client: Annotated[LLMClient, Depends(get_llm_client)],
) -> Response:
    entry = await _own_or_managed_query(ctx, query_id, owner_only=True)
    await repository.set_query_feedback(ctx.session, ctx.workspace_id, query_id, body.value)
    await _sync_approval(ctx, settings, client, entry, body.value)
    await ctx.session.commit()
    return Response(status_code=204)


async def _sync_approval(
    ctx: WorkspaceContext, settings: Settings, client: LLMClient, entry: QueryLog, value: int
) -> None:
    """A thumbs-up makes the query a few-shot example, a thumbs-down withdraws it. Best effort."""
    if entry.data_source_id is None:
        return
    try:
        if value == 1:
            gateway = await _gateway(ctx, settings, client)
            await fewshot.approve_query(ctx.session, gateway, entry=entry, approved_by=ctx.user.id)
        else:
            await fewshot.unapprove_query(
                ctx.session, ctx.workspace_id, entry.data_source_id, entry.question
            )
    except Exception:
        logger.warning("Updating the approved query failed", exc_info=True)
