"""Prompt building and reply parsing for Text-to-SQL (the model never sees more than it needs)."""

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from nawa.data.discovery import TableInfo
from nawa.data.linking import LinkedSchema
from nawa.data.semantic import SemanticModel, allowlist
from nawa.intelligence.gateway import ChatMessage, LLMGateway, TraceInfo
from nawa.intelligence.prompts import PromptRegistry
from nawa.intelligence.untrusted import wrap_untrusted_block

NONE_MATCHED = "(none matched)"
MAX_ERROR_CHARS = 300
MAX_PREVIOUS_SQL_CHARS = 2000
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class SqlGenerationError(ValueError):
    """The model's reply cannot be used. Counts as a repairable failure."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


@dataclass(frozen=True)
class GeneratedSql:
    sql: str | None
    assumptions: list[str]
    clarification: str | None
    raw: str = field(default="", compare=False)


# ---------------------------------------------------------------- reply parsing


def _load_object(text: str) -> Any:
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    if fenced:
        stripped = fenced.group(1)
    try:
        return json.loads(stripped)
    except ValueError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def parse_reply(text: str) -> GeneratedSql:
    try:
        data = _load_object(text)
    except ValueError as exc:
        raise SqlGenerationError("The reply is not valid JSON", text) from exc
    if not isinstance(data, dict) or "sql" not in data:
        raise SqlGenerationError('The reply must be a JSON object with a "sql" key', text)
    sql = data["sql"]
    if sql is not None and not isinstance(sql, str):
        raise SqlGenerationError('"sql" must be a string or null', text)
    assumptions = data.get("assumptions") or []
    if not isinstance(assumptions, list) or not all(isinstance(a, str) for a in assumptions):
        raise SqlGenerationError('"assumptions" must be a list of strings', text)
    clarification = data.get("clarification")
    if clarification is not None and not isinstance(clarification, str):
        raise SqlGenerationError('"clarification" must be a string or null', text)
    return GeneratedSql(
        sql=(sql.strip() or None) if sql is not None else None,
        assumptions=assumptions,
        clarification=clarification,
        raw=text,
    )


# ---------------------------------------------------------------- prompt blocks


def _expand(metrics: dict[str, str], name: str, stack: frozenset[str]) -> exp.Expr:
    node = sqlglot.parse_one(metrics[name], read="postgres")
    inner = stack | {name}

    def inline(found: exp.Expr) -> exp.Expr:
        if (
            isinstance(found, exp.Column)
            and not found.table
            and found.name in metrics
            and found.name not in inner
        ):
            return exp.Paren(this=_expand(metrics, found.name, inner))
        return found

    return node.transform(inline)


def expand_metric(model: SemanticModel, name: str) -> str:
    """The metric's SQL with other metrics it names written out, so the model copies one thing."""
    metrics = {m.name: m.sql for m in model.metrics}
    if name not in metrics:
        return ""
    try:
        expanded = _expand(metrics, name, frozenset())
    except SqlglotError:
        return metrics[name].strip()
    if expanded.sql(dialect="postgres") == sqlglot.parse_one(metrics[name], read="postgres").sql(
        dialect="postgres"
    ):
        return metrics[name].strip()  # nothing to inline: keep the author's own text
    return expanded.sql(dialect="postgres")


def render_metrics(model: SemanticModel, linked: LinkedSchema) -> str:
    lines = []
    for metric in model.metrics:
        if metric.name in linked.metrics:
            note = f" {metric.description}" if metric.description else ""
            lines.append(f"- {metric.name}:{note} SQL: {expand_metric(model, metric.name)}")
    return "\n".join(lines) or NONE_MATCHED


def render_dimensions(model: SemanticModel, linked: LinkedSchema) -> str:
    lines = []
    for dimension in model.dimensions:
        if dimension.name in linked.dimensions:
            note = f" ({dimension.description})" if dimension.description else ""
            lines.append(f"- {dimension.name}: {dimension.sql}{note}")
    return "\n".join(lines) or NONE_MATCHED


def render_schema(linked: LinkedSchema, schema: list[TableInfo], model: SemanticModel) -> str:
    """Tables, allowed columns, keys, joins, and (inside an untrusted block) sample values."""
    allow = allowlist(model)
    known = {t.name: t for t in schema}
    described = {t.name: t for t in model.tables}
    column_notes = {
        (t.name, c.name): c.description for t in model.tables for c in t.columns if c.description
    }
    lines: list[str] = []
    samples: list[dict[str, str]] = []
    joins: list[str] = []
    for name in linked.tables:
        table = known.get(name)
        if table is None or name not in allow:
            continue
        note = f": {described[name].description}" if described[name].description else ""
        lines.append(f"- {name} (about {table.row_estimate} rows){note}")
        foreign = {
            fk.columns[0]: f"{fk.ref_table}.{fk.ref_columns[0]}"
            for fk in table.foreign_keys
            if len(fk.columns) == 1 and fk.ref_table in allow and fk.ref_table in linked.tables
        }
        for fk_column, target in foreign.items():
            joins.append(f"{name}.{fk_column} = {target}")
        for column in table.columns:
            if column.name not in allow[name]:
                continue
            marks = []
            if column.name in table.primary_key:
                marks.append("PK")
            if column.name in foreign:
                marks.append(f"FK -> {foreign[column.name]}")
            tag = f" [{', '.join(marks)}]" if marks else ""
            about = column_notes.get((name, column.name))
            lines.append(f"    {column.name} {column.type}{tag}" + (f" - {about}" if about else ""))
            if column.samples:
                samples.append(
                    {"table": name, "column": column.name, "text": " | ".join(column.samples)}
                )
    linked_names = set(linked.tables)
    for join in model.joins:
        if join.left in linked_names and join.right in linked_names:
            joins.append(join.on)
    unique_joins = list(dict.fromkeys(joins))
    lines.append("JOINS:")
    lines.extend(f"- {j}" for j in unique_joins) if unique_joins else lines.append("(none)")
    if samples:
        lines.append(wrap_untrusted_block("samples", samples))
    return "\n".join(lines)


# ---------------------------------------------------------------- messages and calls


def build_messages(
    registry: PromptRegistry,
    *,
    question: str,
    schema_text: str,
    metrics_text: str,
    dimensions_text: str,
    today: str,
    fewshot_text: str = "",
) -> list[ChatMessage]:
    system = registry.get("text_to_sql").render(
        dialect="PostgreSQL",
        today=today,
        schema_block=schema_text,
        metrics_block=metrics_text,
        dimensions_block=dimensions_text,
        fewshot_block=fewshot_text,
    )
    user = wrap_untrusted_block("question", [{"text": question}])
    return [ChatMessage("system", system), ChatMessage("user", user)]


def repair_messages(
    registry: PromptRegistry,
    base: list[ChatMessage],
    *,
    previous_reply: str,
    previous_sql: str,
    error: str,
) -> list[ChatMessage]:
    prompt = registry.get("sql_repair").render(
        previous_sql=" ".join(previous_sql.split())[:MAX_PREVIOUS_SQL_CHARS] or "(none)",
        error=" ".join(error.split())[:MAX_ERROR_CHARS],
    )
    return [*base, ChatMessage("assistant", previous_reply or "{}"), ChatMessage("user", prompt)]


async def generate_sql(
    gateway: LLMGateway, messages: list[ChatMessage], trace: TraceInfo
) -> GeneratedSql:
    """One model call. Raises `SqlGenerationError` when the reply cannot be parsed."""
    result = await gateway.chat(messages, trace, response_format={"type": "json_object"})
    return replace(parse_reply(result.content), raw=result.content)
