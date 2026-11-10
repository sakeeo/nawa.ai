"""YAML semantic layer: the allowlist, metrics, dimensions, joins and time anchor of a data source.

The YAML is the user-facing format (mappings keyed by name); `SemanticModel` is the canonical
form with lists. A column that is absent from `tables` is not allowlisted, and a column marked
`sensitive` is excluded from the allowlist too (decision P4).
"""

import re
from typing import Any

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlglot import exp
from sqlglot.errors import SqlglotError

from nawa.data.discovery import TableInfo

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOP_LEVEL_KEYS = {"tables", "metrics", "dimensions", "joins", "time_anchor"}


class SemanticError(ValueError):
    """The YAML is malformed or breaks the model's own rules. Messages are user-readable."""

    def __init__(self, problems: list[str] | str) -> None:
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"'{value}' is not a plain identifier (letters, digits, underscore)")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticColumn(_Strict):
    name: str
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    sensitive: bool = False

    _name = field_validator("name")(_identifier)


class SemanticTable(_Strict):
    name: str
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)
    columns: list[SemanticColumn] = Field(default_factory=list)

    _name = field_validator("name")(_identifier)

    @model_validator(mode="after")
    def _unique_columns(self) -> "SemanticTable":
        names = [c.name for c in self.columns]
        if len(names) != len(set(names)):
            raise ValueError(f"table '{self.name}' lists a column twice")
        return self


class Metric(_Strict):
    name: str
    description: str = ""
    sql: str
    synonyms: list[str] = Field(default_factory=list)

    _name = field_validator("name")(_identifier)


class Dimension(_Strict):
    name: str
    sql: str
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)

    _name = field_validator("name")(_identifier)


class Join(_Strict):
    left: str
    right: str
    on: str


class SemanticModel(_Strict):
    tables: list[SemanticTable] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    dimensions: list[Dimension] = Field(default_factory=list)
    joins: list[Join] = Field(default_factory=list)
    time_anchor: str | None = None

    @model_validator(mode="after")
    def _unique_names(self) -> "SemanticModel":
        for label, names in (
            ("table", [t.name for t in self.tables]),
            ("metric", [m.name for m in self.metrics]),
            ("dimension", [d.name for d in self.dimensions]),
        ):
            if len(names) != len(set(names)):
                raise ValueError(f"a {label} name is used twice")
        return self


# ---------------------------------------------------------------- YAML in and out


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of keeping the last one."""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        try:
            key = loader.construct_object(key_node, deep=deep)
            duplicate = key in seen
            seen.add(key)
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                None, None, "mapping keys must be plain values", key_node.start_mark
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key '{key}'", key_node.start_mark
            )
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _load_yaml(text: str) -> Any:
    try:
        # A SafeLoader subclass: it constructs plain data only, never Python objects.
        return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        raise SemanticError(f"Invalid YAML: {problem}") from exc


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SemanticError(f"'{label}' must be a mapping")
    return value


def _parse_join(text: Any) -> dict[str, str]:
    if not isinstance(text, str):
        raise SemanticError("Each join must be a string like 'orders.outlet_id = outlets.id'")
    try:
        node = sqlglot.parse_one(text, read="postgres")
    except SqlglotError as exc:
        raise SemanticError(f"Join '{text}' cannot be parsed") from exc
    if not (
        isinstance(node, exp.EQ)
        and isinstance(node.left, exp.Column)
        and isinstance(node.right, exp.Column)
        and node.left.table
        and node.right.table
        and node.left.table != node.right.table
    ):
        raise SemanticError(
            f"Join '{text}' must equate a column of one table with a column of another"
        )
    left, right = node.left, node.right
    return {
        "left": left.table,
        "right": right.table,
        "on": f"{left.table}.{left.name} = {right.table}.{right.name}",
    }


def _normalize(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SemanticError("The semantic model must be a YAML mapping")
    unknown = sorted(set(raw) - TOP_LEVEL_KEYS)
    if unknown:
        raise SemanticError(f"Unknown top-level key(s): {', '.join(map(str, unknown))}")

    tables: list[dict[str, Any]] = []
    for name, body in _mapping(raw.get("tables"), "tables").items():
        body = dict(_mapping(body, f"tables.{name}"))
        columns: list[Any] = []
        raw_columns = body.pop("columns", [])
        if not isinstance(raw_columns, list):
            raise SemanticError(f"'tables.{name}.columns' must be a list")
        for column in raw_columns:
            columns.append({"name": column} if isinstance(column, str) else column)
        tables.append({**body, "name": name, "columns": columns})

    metrics = [
        {**_mapping(body, f"metrics.{name}"), "name": name}
        for name, body in _mapping(raw.get("metrics"), "metrics").items()
    ]
    dimensions = [
        {"name": name, "sql": body}
        if isinstance(body, str)
        else {**_mapping(body, f"dimensions.{name}"), "name": name}
        for name, body in _mapping(raw.get("dimensions"), "dimensions").items()
    ]
    joins_raw = raw.get("joins") or []
    if not isinstance(joins_raw, list):
        raise SemanticError("'joins' must be a list")
    return {
        "tables": tables,
        "metrics": metrics,
        "dimensions": dimensions,
        "joins": [_parse_join(j) for j in joins_raw],
        "time_anchor": raw.get("time_anchor"),
    }


def parse_semantic_yaml(text: str) -> SemanticModel:
    canonical = _normalize(_load_yaml(text))
    try:
        return SemanticModel.model_validate(canonical)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}".lstrip(": ")
            for err in exc.errors()
        ]
        raise SemanticError(problems) from exc


def to_yaml(model: SemanticModel) -> str:
    tables: dict[str, Any] = {}
    for table in model.tables:
        body: dict[str, Any] = {}
        if table.description:
            body["description"] = table.description
        if table.synonyms:
            body["synonyms"] = table.synonyms
        columns: list[Any] = []
        for column in table.columns:
            extras = column.model_dump(exclude={"name"}, exclude_defaults=True)
            columns.append({"name": column.name, **extras} if extras else column.name)
        body["columns"] = columns
        tables[table.name] = body
    metrics = {m.name: m.model_dump(exclude={"name"}, exclude_defaults=True) for m in model.metrics}
    dimensions: dict[str, Any] = {}
    for dimension in model.dimensions:
        extras = dimension.model_dump(exclude={"name", "sql"}, exclude_defaults=True)
        dimensions[dimension.name] = {"sql": dimension.sql, **extras} if extras else dimension.sql
    raw: dict[str, Any] = {"tables": tables}
    if metrics:
        raw["metrics"] = metrics
    if dimensions:
        raw["dimensions"] = dimensions
    if model.joins:
        raw["joins"] = [j.on for j in model.joins]
    if model.time_anchor:
        raw["time_anchor"] = model.time_anchor
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------- derived views


def allowlist(model: SemanticModel) -> dict[str, set[str]]:
    """Table to allowed columns. Sensitive columns are excluded (decision P4)."""
    return {t.name: {c.name for c in t.columns if not c.sensitive} for t in model.tables}


def draft_from_schema(schema: list[TableInfo]) -> SemanticModel:
    """A starting point without any model call: every table and column, joins from foreign keys."""
    tables = [
        SemanticTable(name=t.name, columns=[SemanticColumn(name=c.name) for c in t.columns])
        for t in schema
    ]
    joins = [
        Join(left=t.name, right=fk.ref_table, on=f"{t.name}.{col} = {fk.ref_table}.{ref}")
        for t in schema
        for fk in t.foreign_keys
        for col, ref in zip(fk.columns, fk.ref_columns, strict=True)
    ]
    return SemanticModel(tables=tables, joins=joins)


# ---------------------------------------------------------------- validation


def _parse_expression(label: str, sql: str, problems: list[str]) -> exp.Condition | None:
    try:
        node = sqlglot.parse_one(sql, read="postgres")
    except SqlglotError:
        problems.append(f"{label}: SQL cannot be parsed")
        return None
    if not isinstance(node, exp.Condition) or node.find(exp.Query):
        problems.append(f"{label}: must be a plain SQL expression, not a statement or subquery")
        return None
    return node


def _metric_cycle(metrics: dict[str, set[str]]) -> str | None:
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(name: str) -> str | None:
        if name in done:
            return None
        if name in visiting:
            return name
        visiting.add(name)
        for ref in metrics.get(name, set()):
            if ref in metrics and (found := visit(ref)):
                return found
        visiting.discard(name)
        done.add(name)
        return None

    return next((hit for name in metrics if (hit := visit(name))), None)


def validate_against_schema(model: SemanticModel, schema: list[TableInfo]) -> list[str]:
    """Problems found when the model is checked against the discovered schema (empty is valid)."""
    problems: list[str] = []
    columns_of = {t.name: {c.name for c in t.columns} for t in schema}
    listed = {t.name for t in model.tables}
    allowed = allowlist(model)

    for table in model.tables:
        if table.name not in columns_of:
            problems.append(f"Table '{table.name}' does not exist in the data source")
            continue
        for column in table.columns:
            if column.name not in columns_of[table.name]:
                problems.append(f"Column '{table.name}.{column.name}' does not exist")

    def check_column(label: str, table: str, column: str) -> None:
        if table not in listed:
            problems.append(f"{label}: table '{table}' is not in the semantic model")
        elif column not in allowed[table] or column not in columns_of.get(table, set()):
            problems.append(f"{label}: column '{table}.{column}' is not allowlisted")

    for join in model.joins:
        label = f"Join '{join.on}'"
        left, right = (side.strip() for side in join.on.split("="))
        for side in (left, right):
            side_table, _, side_column = side.partition(".")
            check_column(label, side_table, side_column)

    metric_names = {m.name for m in model.metrics}
    references: dict[str, set[str]] = {}
    expressions = [(f"Metric '{m.name}'", m.name, m.sql) for m in model.metrics] + [
        (f"Dimension '{d.name}'", None, d.sql) for d in model.dimensions
    ]
    for label, metric_name, sql in expressions:
        node = _parse_expression(label, sql, problems)
        if node is None:
            continue
        for ref in node.find_all(exp.Column):
            if ref.table:
                check_column(label, ref.table, ref.name)
            elif ref.name in metric_names:
                if metric_name is not None:
                    references.setdefault(metric_name, set()).add(ref.name)
            else:
                problems.append(
                    f"{label}: unknown name '{ref.name}' (write columns as table.column)"
                )
    if (cyclic := _metric_cycle(references)) is not None:
        problems.append(f"Metric '{cyclic}' references itself through other metrics")

    if model.time_anchor is not None:
        _check_time_anchor(model.time_anchor, listed, allowed, problems)
    return problems


def _check_time_anchor(
    anchor: str, listed: set[str], allowed: dict[str, set[str]], problems: list[str]
) -> None:
    label = "time_anchor"
    try:
        statements = [s for s in sqlglot.parse(anchor, read="postgres") if s is not None]
    except SqlglotError:
        problems.append(f"{label}: SQL cannot be parsed")
        return
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        problems.append(f"{label}: must be a single SELECT statement")
        return
    select = statements[0]
    tables = {t.name for t in select.find_all(exp.Table)}
    for table in sorted(tables - listed):
        problems.append(f"{label}: table '{table}' is not in the semantic model")
    known = tables & listed
    for column in select.find_all(exp.Column):
        if column.table:
            if column.table in listed and column.name not in allowed[column.table]:
                problems.append(
                    f"{label}: column '{column.table}.{column.name}' is not allowlisted"
                )
        elif known and not any(column.name in allowed[t] for t in known):
            problems.append(f"{label}: column '{column.name}' is not allowlisted")
