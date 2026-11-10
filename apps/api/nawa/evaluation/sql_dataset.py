"""Loader for the Text-to-SQL golden dataset (`evals/sql_golden.yaml`)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from nawa.data.guard import check_sql
from nawa.evaluation.dataset import DatasetError

DIFFICULTIES = ("easy", "medium", "hard")
EXPECTED_COUNTS = {"easy": 20, "medium": 20, "hard": 10}
EXPECTED_DANGEROUS = 10

_ITEM_KEYS = {"id", "difficulty", "question", "reference_sql", "ordered", "tags"}
_ITEM_REQUIRED = _ITEM_KEYS - {"tags"}
_DANGER_KEYS = {"id", "kind", "question"}


@dataclass(frozen=True)
class SqlItem:
    id: str
    difficulty: str
    question: str
    reference_sql: str
    ordered: bool
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DangerItem:
    id: str
    kind: str
    question: str


def _text(raw: dict[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{where}: '{key}' must be non-empty text")
    return value.strip()


def _mapping(raw: Any, where: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DatasetError(f"{where}: must be a mapping")
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise DatasetError(f"{where}: unknown key(s) {', '.join(map(str, unknown))}")
    missing = sorted(required - set(raw))
    if missing:
        raise DatasetError(f"{where}: missing key(s) {', '.join(missing)}")
    return raw


def _answerable(raw: Any, number: int) -> SqlItem:
    where = f"answerable item #{number}"
    data = _mapping(raw, where, _ITEM_KEYS, _ITEM_REQUIRED)
    item_id = _text(data, "id", where)
    where = f"{item_id}"
    difficulty = _text(data, "difficulty", where)
    if difficulty not in DIFFICULTIES:
        raise DatasetError(f"{where}: 'difficulty' must be one of {', '.join(DIFFICULTIES)}")
    if not isinstance(data["ordered"], bool):
        raise DatasetError(f"{where}: 'ordered' must be true or false")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise DatasetError(f"{where}: 'tags' must be a list of strings")
    return SqlItem(
        id=item_id,
        difficulty=difficulty,
        question=_text(data, "question", where),
        reference_sql=_text(data, "reference_sql", where),
        ordered=data["ordered"],
        tags=tuple(tags),
    )


def _dangerous(raw: Any, number: int) -> DangerItem:
    where = f"dangerous item #{number}"
    data = _mapping(raw, where, _DANGER_KEYS, _DANGER_KEYS)
    item_id = _text(data, "id", where)
    return DangerItem(
        id=item_id,
        kind=_text(data, "kind", item_id),
        question=_text(data, "question", item_id),
    )


def load_sql_golden(
    path: Path,
    *,
    allow: dict[str, set[str]] | None = None,
    enforce_counts: bool = True,
) -> tuple[list[SqlItem], list[DangerItem]]:
    """Read and validate the dataset.

    With `allow` (table to allowed columns) every reference SQL must also pass the SQL Guard, so
    references obey the same rules as model SQL. `enforce_counts` checks 20/20/10 answerable
    items and 10 dangerous ones.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DatasetError(f"Golden file not found: {path}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DatasetError(f"Golden file is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise DatasetError("Golden file must be a mapping with 'answerable' and 'dangerous'")
    unknown = sorted(set(document) - {"answerable", "dangerous"})
    if unknown:
        raise DatasetError(f"Golden file has unknown key(s): {', '.join(map(str, unknown))}")
    for key in ("answerable", "dangerous"):
        if not isinstance(document.get(key), list):
            raise DatasetError(f"Golden file needs a list under '{key}'")

    items = [_answerable(raw, n) for n, raw in enumerate(document["answerable"], start=1)]
    dangerous = [_dangerous(raw, n) for n, raw in enumerate(document["dangerous"], start=1)]

    seen: set[str] = set()
    for item_id in [i.id for i in items] + [d.id for d in dangerous]:
        if item_id in seen:
            raise DatasetError(f"Duplicate id: {item_id}")
        seen.add(item_id)

    if enforce_counts:
        for difficulty, expected in EXPECTED_COUNTS.items():
            found = sum(1 for i in items if i.difficulty == difficulty)
            if found != expected:
                raise DatasetError(f"{difficulty}: expected {expected} items, found {found}")
        if len(dangerous) != EXPECTED_DANGEROUS:
            raise DatasetError(
                f"dangerous: expected {EXPECTED_DANGEROUS} items, found {len(dangerous)}"
            )

    if allow is not None:
        for item in items:
            verdict = check_sql(item.reference_sql, allow)
            if not verdict.ok:
                raise DatasetError(
                    f"{item.id}: reference_sql rejected by the SQL guard ({verdict.reason})"
                )
    return items, dangerous
