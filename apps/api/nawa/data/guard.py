"""SQL Guard: parser, allowlist and limit enforcement for model-generated SQL (layers 1-3).

`check_sql` is pure: it never touches a database. It returns the SQL to execute, rewritten so
that `*` only expands to allowlisted columns and the outermost query has a `LIMIT`. Only that
rewritten SQL may be executed, and only through `nawa.data.executor`.

Failure kinds drive the self-correction policy (decision P6):
  - `repairable`: syntax error, unknown column, unknown function, unsupported form. The model
    may try again.
  - `forbidden`: anything that is not a single read-only SELECT over allowlisted tables, or that
    reads a table, schema or function it must not. Final, never retried.
"""

import re
from dataclasses import dataclass
from typing import Literal, NewType

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.qualify import qualify

Kind = Literal["ok", "repairable", "forbidden"]

FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "pg_sleep",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "dblink",
        "dblink_exec",
        "set_config",
        "current_setting",
        "query_to_xml",
        "query_to_xmlschema",
        "table_to_xml",
        "cursor_to_xml",
        "database_to_xml",
        "xpath",
        "lo_import",
        "lo_export",
        "lo_get",
        "lo_put",
        "copy_from",
        "row_to_json",
        "to_json",
        "to_jsonb",
        "json_agg",
        "jsonb_agg",
        "version",
        "current_user",
        "session_user",
        "inet_server_addr",
    }
)
FORBIDDEN_PREFIXES = ("pg_", "lo_", "dblink")

ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # aggregates
        "COUNT", "SUM", "AVG", "MIN", "MAX", "STDDEV", "STDDEV_POP", "STDDEV_SAMP", "VARIANCE",
        "VAR_POP", "VAR_SAMP", "STRING_AGG", "BOOL_AND", "BOOL_OR", "ANY_VALUE",
        "PERCENTILE_CONT", "PERCENTILE_DISC",
        # date and time
        "DATE_TRUNC", "EXTRACT", "DATE_PART", "AGE", "NOW", "CURRENT_DATE", "CURRENT_TIMESTAMP",
        "CURRENT_TIME", "LOCALTIME", "LOCALTIMESTAMP", "TO_CHAR", "TO_DATE", "TO_TIMESTAMP",
        "MAKE_DATE", "DATE_ADD", "DATE_SUB", "DATETIME_ADD", "DATETIME_SUB", "TIMESTAMP_ADD",
        "TIMESTAMP_SUB", "TS_OR_DS_ADD", "TS_OR_DS_TO_DATE", "TS_OR_DS_TO_TIMESTAMP",
        # text
        "LOWER", "UPPER", "LENGTH", "CHAR_LENGTH", "TRIM", "LTRIM", "RTRIM", "BTRIM", "SUBSTRING",
        "SUBSTR", "CONCAT", "CONCAT_WS", "REPLACE", "LEFT", "RIGHT", "POSITION", "STRPOS",
        "INITCAP", "SPLIT_PART", "LPAD", "RPAD", "REVERSE",
        # math
        "ROUND", "CEIL", "CEILING", "FLOOR", "ABS", "POWER", "POW", "SQRT", "MOD", "SIGN", "LN",
        "LOG", "EXP", "GREATEST", "LEAST", "TRUNC", "DIV", "TO_NUMBER",
        # conditional and conversion
        "COALESCE", "NULLIF", "CAST", "TRY_CAST", "CASE", "IF", "EXISTS",
        # window
        "ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
        "NTH_VALUE", "PERCENT_RANK", "CUME_DIST",
    }
)  # fmt: skip

_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command", "Copy", "Grant",
    "Revoke", "TruncateTable", "Set", "Into", "Lock", "Use", "Pragma", "Transaction", "Commit",
    "Rollback", "Analyze", "Kill",
)  # fmt: skip
_FORBIDDEN_NODES: tuple[type[exp.Expr], ...] = tuple(
    getattr(exp, name) for name in _FORBIDDEN_NODE_NAMES if hasattr(exp, name)
)

_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_QUALIFIED_CALL = re.compile(r"[A-Za-z0-9_\"]\s*\.\s*\"?[A-Za-z_][A-Za-z0-9_]*\"?\s*\(")
_FIRST_TOKEN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)")
_AUTO_ALIAS = re.compile(r"_col_\d+")


# SQL that passed `check_sql`. The executor accepts only this type, so unchecked text cannot
# reach a database by accident (mypy enforces it; `mark_checked` is the one way to make it).
GuardedSql = NewType("GuardedSql", str)


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str | None
    kind: Kind
    reason: str | None
    tables: frozenset[str]


def _fail(kind: Kind, reason: str, tables: frozenset[str] = frozenset()) -> GuardResult:
    return GuardResult(ok=False, sql=None, kind=kind, reason=reason, tables=tables)


def _is_forbidden_function(name: str) -> bool:
    lowered = name.lower()
    return lowered in FORBIDDEN_FUNCTIONS or lowered.startswith(FORBIDDEN_PREFIXES)


def _function_names(node: exp.Func) -> set[str]:
    if isinstance(node, exp.Anonymous):
        return {str(node.name).upper()}
    names = {node.sql_name().upper()}
    match = _FIRST_TOKEN.match(node.sql(dialect="postgres", comments=False))
    if match:
        names.add(match.group(1).upper())
    return names


def _visible_ctes(node: exp.Expr) -> set[str]:
    """CTE names a table reference can see (a CTE body sees earlier siblings, not itself)."""
    names: set[str] = set()
    child: exp.Expr = node
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.With):
            for cte in parent.expressions:
                if cte is child:
                    if parent.args.get("recursive"):
                        names.add(cte.alias)
                    break
                names.add(cte.alias)
        else:
            with_clause = parent.args.get("with_")
            if isinstance(with_clause, exp.With) and child is not with_clause:
                names.update(cte.alias for cte in with_clause.expressions)
        child, parent = parent, parent.parent
    return names


def _check_tables(root: exp.Expr, allow: dict[str, set[str]]) -> GuardResult | None:
    """Layer 2 for tables. Returns a failure, or None when every table is acceptable."""
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            continue  # a table-valued function: the function check decides
        name, schema = table.name, table.db
        if table.catalog:
            return _fail("forbidden", "Cross-database references are not allowed")
        if schema and schema != "public":
            return _fail("forbidden", f"Schema '{schema}' is not accessible")
        alias = table.args.get("alias")
        if isinstance(alias, exp.TableAlias) and alias.columns:
            return _fail("forbidden", "Renaming table columns in an alias is not allowed")
        if not schema and name in _visible_ctes(table):
            continue
        if name not in allow:
            return _fail("forbidden", f"Table '{name}' is not available")
    return None


def _check_functions(root: exp.Expr) -> GuardResult | None:
    for node in root.find_all(exp.Func):
        if isinstance(node, (exp.Binary, exp.Unary, exp.Connector)):
            continue  # operators such as AND, OR, NOT, %: they cannot name a function
        names = _function_names(node)
        for name in names:
            if _is_forbidden_function(name):
                return _fail("forbidden", f"Function '{name.lower()}' is not allowed")
        if not names & ALLOWED_FUNCTIONS:
            shown = sorted(names)[0].lower()
            return _fail("repairable", f"Function '{shown}' is not available")
    return None


def _scan_rendered(sql: str) -> GuardResult | None:
    """Defense in depth: look for forbidden function calls in the final text."""
    text = _STRING_LITERAL.sub("''", sql)
    if _QUALIFIED_CALL.search(text):
        return _fail("forbidden", "Schema-qualified function calls are not allowed")
    for name in _CALL.findall(text):
        if _is_forbidden_function(name):
            return _fail("forbidden", f"Function '{name.lower()}' is not allowed")
    return None


def _apply_limit(root: exp.Expr, max_rows: int) -> GuardResult | None:
    existing = root.args.get("limit")
    if isinstance(existing, exp.Fetch):
        return _fail("repairable", "Use LIMIT instead of FETCH FIRST")
    keep = False
    if isinstance(existing, exp.Limit):
        value = existing.expression
        keep = isinstance(value, exp.Literal) and value.is_int and int(value.this) <= max_rows
    if not keep:
        root.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return None


def check_sql(sql: str, allow: dict[str, set[str]], *, max_rows: int = 1000) -> GuardResult:
    """Validate and rewrite `sql`. `allow` maps table to its allowed columns."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        detail = exc.errors[0].get("description", "") if exc.errors else ""
        return _fail("repairable", f"Syntax error: {str(detail)[:100] or 'cannot parse the query'}")
    except SqlglotError:
        return _fail("repairable", "Syntax error: cannot parse the query")
    if not statements:
        return _fail("repairable", "The query is empty")
    if len(statements) > 1:
        return _fail("forbidden", "Only one statement is allowed")

    root = statements[0].unnest()
    if not isinstance(root, exp.Query) or root.find(*_FORBIDDEN_NODES):
        return _fail("forbidden", "Only a single read-only SELECT query is allowed")

    root = normalize_identifiers(root.copy(), dialect="postgres")
    if (failure := _check_tables(root, allow)) or (failure := _check_functions(root)):
        return failure
    tables = frozenset(
        t.name
        for t in root.find_all(exp.Table)
        if isinstance(t.this, exp.Identifier) and t.name in allow
    )

    schema: dict[str, object] = {
        table: {column: "TEXT" for column in columns} for table, columns in allow.items()
    }
    try:
        qualified = qualify(
            root.copy(),
            schema=schema,
            dialect="postgres",
            validate_qualify_columns=True,
            identify=False,
        )
    except SqlglotError as exc:
        return _fail("repairable", f"Cannot resolve columns: {str(exc).splitlines()[0][:100]}")
    except Exception:
        return _fail("repairable", "The query structure could not be resolved")

    # A bare table or alias used as a value is a whole-row reference (it would return columns
    # that are not allowlisted). sqlglot marks it as TableColumn.
    if qualified.find(exp.TableColumn):
        return _fail("forbidden", "A table cannot be selected as a whole row")
    sources = {t.alias_or_name for t in qualified.find_all(exp.Table)}
    sources |= {s.alias for s in qualified.find_all(exp.Subquery) if s.alias}
    sources |= {c.alias for c in qualified.find_all(exp.CTE)}
    for column in qualified.find_all(exp.Column):
        if not column.table and column.name in sources:
            return _fail("forbidden", f"'{column.name}' cannot be selected as a whole row")
    for star in qualified.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            return _fail("forbidden", "A '*' could not be limited to allowed columns")
    for alias in list(qualified.find_all(exp.Alias)):
        if _AUTO_ALIAS.fullmatch(alias.alias):
            alias.replace(alias.this)

    if failure := _apply_limit(qualified, max_rows):
        return failure
    rendered = qualified.sql(dialect="postgres", comments=False)
    if failure := _scan_rendered(rendered):
        return failure
    return GuardResult(ok=True, sql=rendered, kind="ok", reason=None, tables=tables)


def mark_checked(result: GuardResult) -> GuardedSql:
    """Turn a successful guard result into executable SQL. Refuses anything else."""
    if not result.ok or result.sql is None:
        raise ValueError("Only SQL that passed the guard can be executed")
    return GuardedSql(result.sql)
