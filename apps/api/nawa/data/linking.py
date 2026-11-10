"""Schema linking: pick the tables, metrics and dimensions a question needs (decision P10).

Only what is linked goes into the Text-to-SQL prompt. A table scores by a lexical match on its
name and synonyms, or by the cosine of `bge-m3` embeddings. Metrics and dimensions that match
pull in the tables their SQL uses, and bridge tables are added so the chosen tables can be
joined over foreign keys. With no usable embeddings the linking is lexical only.
"""

import logging
import math
import re
import uuid
from collections import deque
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from nawa.data.discovery import TableInfo
from nawa.data.semantic import SemanticModel
from nawa.intelligence.gateway import LLMGateway

logger = logging.getLogger("nawa.data.linking")

SEMANTIC_MIN = 0.45  # cosine below this is noise; calibrated against the golden set in T2-14
ITEM_MIN = 0.5  # a metric or dimension counts as mentioned from this score
PULL_FACTOR = 0.95  # a mentioned metric lifts its tables to almost the same score
VALUE_SCORE = 0.7  # the question names a sample value of one of the table's columns
CACHE_SIZE = 64

_WORD = re.compile(r"[^\W_]+")
_INDEX_CACHE: dict[tuple[uuid.UUID, int], "LinkIndex"] = {}


@dataclass(frozen=True)
class LinkedSchema:
    tables: list[str]
    metrics: list[str]
    dimensions: list[str]
    scores: dict[str, float]


@dataclass(frozen=True)
class LinkIndex:
    semantic: bool
    tables: list[str]
    metrics: list[str]
    dimensions: list[str]
    terms: dict[str, list[str]]
    vectors: dict[str, list[float]] = field(default_factory=dict)
    item_tables: dict[str, frozenset[str]] = field(default_factory=dict)
    metric_refs: dict[str, frozenset[str]] = field(default_factory=dict)
    join_pairs: list[tuple[str, str]] = field(default_factory=list)
    columns: dict[str, frozenset[str]] = field(default_factory=dict)


# ---------------------------------------------------------------- lexical matching


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("nya"):  # Indonesian possessive: stoknya -> stok
        token = token[:-3]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token


def _tokens(text: str) -> list[str]:
    return [_stem(token) for token in _WORD.findall(text.lower())]


def _contains(haystack: list[str], needle: list[str]) -> bool:
    size = len(needle)
    return any(haystack[i : i + size] == needle for i in range(len(haystack) - size + 1))


def lexical_hits(question: str, terms: dict[str, list[str]]) -> dict[str, float]:
    """Keys whose name or synonym appears in the question as whole words (score 1.0)."""
    question_tokens = _tokens(question)
    hits: dict[str, float] = {}
    for key, key_terms in terms.items():
        for term in key_terms:
            tokens = _tokens(term)
            if not tokens or all(len(token) < 2 for token in tokens):
                continue
            if _contains(question_tokens, tokens):
                hits[key] = 1.0
                break
    return hits


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


# ---------------------------------------------------------------- index


def _expression_refs(sql: str) -> tuple[set[str], set[str]]:
    """Tables named by `table.column` references, and bare names (other metrics)."""
    try:
        node = sqlglot.parse_one(sql, read="postgres")
    except SqlglotError:
        return set(), set()
    columns = list(node.find_all(exp.Column))
    return {c.table for c in columns if c.table}, {c.name for c in columns if not c.table}


def _closure(name: str, refs: dict[str, frozenset[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(refs.get(current, ()))
    return seen


def _text(name: str, description: str, synonyms: list[str]) -> str:
    return " ".join([name, description, *synonyms]).strip()


async def build_link_index(
    gateway: LLMGateway, model: SemanticModel, model_key: tuple[uuid.UUID, int]
) -> LinkIndex:
    """Embed the semantic model once per `(semantic_model_id, version)` and cache the result."""
    cached = _INDEX_CACHE.get(model_key)
    if cached is not None:
        return cached

    texts: dict[str, str] = {}
    terms: dict[str, list[str]] = {}
    for table in model.tables:
        key = f"table:{table.name}"
        column_synonyms = [s for c in table.columns for s in c.synonyms]
        texts[key] = _text(table.name, table.description, table.synonyms)
        terms[key] = [table.name, *table.synonyms, *column_synonyms]
    for metric in model.metrics:
        key = f"metric:{metric.name}"
        texts[key] = _text(metric.name, metric.description, metric.synonyms)
        terms[key] = [metric.name, *metric.synonyms]
    for dimension in model.dimensions:
        key = f"dimension:{dimension.name}"
        texts[key] = _text(dimension.name, dimension.description, dimension.synonyms)
        terms[key] = [dimension.name, *dimension.synonyms]

    table_names = {t.name for t in model.tables}
    refs: dict[str, frozenset[str]] = {}
    item_tables: dict[str, frozenset[str]] = {}
    direct: dict[str, set[str]] = {}
    for metric in model.metrics:
        found, bare = _expression_refs(metric.sql)
        direct[metric.name] = found & table_names
        refs[metric.name] = frozenset(bare & {m.name for m in model.metrics})
    for metric in model.metrics:
        merged: set[str] = set()
        for name in _closure(metric.name, refs):
            merged |= direct.get(name, set())
        item_tables[f"metric:{metric.name}"] = frozenset(merged)
    for dimension in model.dimensions:
        found, _ = _expression_refs(dimension.sql)
        item_tables[f"dimension:{dimension.name}"] = frozenset(found & table_names)

    vectors: dict[str, list[float]] = {}
    semantic = False
    cacheable = True
    try:
        embedded = await gateway.embed(list(texts.values()))
        if len(embedded) == len(texts) and any(any(vector) for vector in embedded):
            vectors = dict(zip(texts, embedded, strict=True))
            semantic = True
    except Exception:
        logger.warning(
            "Embedding the semantic model failed; linking is lexical only", exc_info=True
        )
        cacheable = False

    index = LinkIndex(
        semantic=semantic,
        tables=[t.name for t in model.tables],
        metrics=[m.name for m in model.metrics],
        dimensions=[d.name for d in model.dimensions],
        terms=terms,
        vectors=vectors,
        item_tables=item_tables,
        metric_refs=refs,
        join_pairs=[(j.left, j.right) for j in model.joins],
        columns={
            t.name: frozenset(c.name for c in t.columns if not c.sensitive) for t in model.tables
        },
    )
    if cacheable:
        if len(_INDEX_CACHE) >= CACHE_SIZE:
            _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
        _INDEX_CACHE[model_key] = index
    return index


# ---------------------------------------------------------------- linking


def _adjacency(
    allowed: set[str], schema: list[TableInfo], join_pairs: list[tuple[str, str]]
) -> dict[str, list[str]]:
    edges: dict[str, set[str]] = {name: set() for name in allowed}
    pairs = list(join_pairs)
    for table in schema:
        pairs.extend((table.name, fk.ref_table) for fk in table.foreign_keys)
    for left, right in pairs:
        if left in allowed and right in allowed and left != right:
            edges[left].add(right)
            edges[right].add(left)
    return {name: sorted(neighbors) for name, neighbors in edges.items()}


def _path_to(adjacency: dict[str, list[str]], tree: set[str], target: str) -> list[str]:
    """Shortest path from any table in `tree` to `target`; empty when unreachable."""
    parents: dict[str, str | None] = {name: None for name in sorted(tree)}
    queue = deque(sorted(tree))
    while queue:
        current = queue.popleft()
        if current == target:
            path = []
            node: str | None = current
            while node is not None:
                path.append(node)
                node = parents[node]
            return path
        for neighbor in adjacency.get(current, []):
            if neighbor not in parents:
                parents[neighbor] = current
                queue.append(neighbor)
    return []


def _connect(selected: list[str], adjacency: dict[str, list[str]]) -> set[str]:
    tree = {selected[0]}
    for target in selected[1:]:
        if target in tree:
            continue
        tree.update(_path_to(adjacency, tree, target) or [target])
    return tree


async def link_schema(
    index: LinkIndex,
    gateway: LLMGateway,
    question: str,
    schema: list[TableInfo],
    *,
    top_tables: int = 4,
) -> LinkedSchema:
    known = {t.name: t for t in schema}
    allowed = [name for name in index.tables if name in known]

    question_vector: list[float] | None = None
    if index.semantic and question.strip():
        try:
            question_vector = (await gateway.embed([question]))[0]
        except Exception:
            logger.warning("Embedding the question failed; linking is lexical only", exc_info=True)

    lexical = lexical_hits(question, index.terms)
    cosines: dict[str, float] = {}
    scores: dict[str, float] = {}
    for key in index.terms:
        score = lexical.get(key, 0.0)
        if question_vector is not None:
            cosines[key] = _cosine(question_vector, index.vectors[key])
            if cosines[key] >= SEMANTIC_MIN:
                score = max(score, cosines[key])
        scores[key] = score

    for name in allowed:  # "di Bandung": a sample value of an allowlisted column names the table
        allowed_columns = index.columns.get(name, frozenset())
        values = [v for c in known[name].columns if c.name in allowed_columns for v in c.samples]
        if values and lexical_hits(question, {name: values}):
            scores[f"table:{name}"] = max(scores[f"table:{name}"], VALUE_SCORE)

    mentioned: dict[str, float] = {}
    for kind, names in (("metric", index.metrics), ("dimension", index.dimensions)):
        for name in names:
            if scores[f"{kind}:{name}"] >= ITEM_MIN:
                mentioned[f"{kind}:{name}"] = scores[f"{kind}:{name}"]
    for name in index.metrics:  # a metric built on another metric needs that one too
        if f"metric:{name}" in mentioned:
            for dependency in _closure(name, index.metric_refs) - {name}:
                mentioned.setdefault(f"metric:{dependency}", ITEM_MIN)

    table_scores = {name: scores[f"table:{name}"] for name in allowed}
    for key, item_score in mentioned.items():
        for table in index.item_tables.get(key, frozenset()):
            if table in table_scores:
                table_scores[table] = max(table_scores[table], item_score * PULL_FACTOR)

    if len(allowed) <= top_tables:
        chosen = set(allowed)
    else:
        ranked = sorted(
            (n for n in allowed if table_scores[n] > 0), key=lambda n: (-table_scores[n], n)
        )
        selected = ranked[:top_tables]
        if not selected:
            if question_vector is not None:
                fallback = sorted(allowed, key=lambda n: (-cosines[f"table:{n}"], n))
            else:
                fallback = sorted(allowed, key=lambda n: (-known[n].row_estimate, n))
            selected = fallback[:top_tables]
        chosen = _connect(selected, _adjacency(set(allowed), schema, index.join_pairs))

    return LinkedSchema(
        tables=[name for name in allowed if name in chosen],
        metrics=[n for n in index.metrics if f"metric:{n}" in mentioned],
        dimensions=[n for n in index.dimensions if f"dimension:{n}" in mentioned],
        scores={key: round(value, 4) for key, value in scores.items() if value > 0},
    )
