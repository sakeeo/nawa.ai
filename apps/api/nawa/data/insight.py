"""Statistics, number grounding and the insight text for a query result (decision P9).

The model may only phrase numbers that exist in the result or in the statistics computed here.
Every number in its text is checked; a text with an unknown number is replaced by a
deterministic template that is grounded by construction.
"""

import json
import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from nawa.data.charts import column_kinds
from nawa.intelligence.gateway import ChatMessage, LLMGateway, LLMUnavailableError, TraceInfo
from nawa.intelligence.prompts import PromptRegistry
from nawa.intelligence.untrusted import wrap_untrusted_block

logger = logging.getLogger("nawa.data")

MAX_PROMPT_ROWS = 50
MAX_CELL_CHARS = 80
NO_DATA = "Tidak ada data untuk pertanyaan ini."

_MULTIPLIERS = {
    "ribu": 1e3,
    "juta": 1e6,
    "jt": 1e6,
    "miliar": 1e9,
    "milyar": 1e9,
    "triliun": 1e12,
}
_DATE_OR_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?"
    r"|\d{4}-\d{2}(?!\d)"
    r"|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"
)
_LIST_NUMBER = re.compile(r"(?m)^\s*\d+[.)]\s+")
_RUPIAH = re.compile(r"\bRp\.?\s*", re.IGNORECASE)
_NUMBER = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s*(?:(%)|(ribu|juta|jt|miliar|milyar|triliun)\b))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InsightResult:
    text: str
    grounded: bool
    used_fallback: bool


# ---------------------------------------------------------------- statistics


def _round(value: float) -> float:
    return round(float(value), 2)


def _label(value: Any) -> str:
    text = str(value)
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", text) else text


def compute_stats(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    """Facts the insight may quote: per-column totals, ranking, shares and first-to-last change."""
    kinds = column_kinds(columns, rows)
    position = {name: index for index, name in enumerate(columns)}
    numeric = [c for c in columns if kinds[c] == "numeric"]
    categorical = [c for c in columns if kinds[c] == "categorical"]
    temporal = [c for c in columns if kinds[c] == "temporal"]
    stats: dict[str, Any] = {"row_count": len(rows), "columns": {}}

    for name in numeric:
        values = [row[position[name]] for row in rows if row[position[name]] is not None]
        stats["columns"][name] = {
            "sum": _round(sum(values)),
            "min": _round(min(values)),
            "max": _round(max(values)),
            "mean": _round(sum(values) / len(values)),
        }
    if not numeric:
        return stats

    value_name = numeric[0]
    value_at = position[value_name]
    if len(categorical) == 1 and not temporal:
        label_at = position[categorical[0]]
        pairs = [(str(r[label_at]), r[value_at]) for r in rows if r[value_at] is not None]
        top = max(pairs, key=lambda p: p[1])
        bottom = min(pairs, key=lambda p: p[1])
        ranking: dict[str, Any] = {
            "label_column": categorical[0],
            "value_column": value_name,
            "top": {"label": top[0], "value": _round(top[1])},
            "bottom": {"label": bottom[0], "value": _round(bottom[1])},
        }
        total = sum(value for _, value in pairs)
        if total > 0 and all(value >= 0 for _, value in pairs):
            ranking["shares"] = [
                {"label": label, "share_pct": _round(value / total * 100)} for label, value in pairs
            ]
        stats["ranking"] = ranking
    elif len(temporal) == 1 and not categorical and len(rows) >= 2:
        at = position[temporal[0]]
        series = sorted(
            ((_label(r[at]), r[value_at]) for r in rows if r[value_at] is not None),
            key=lambda p: p[0],
        )
        first, last = series[0], series[-1]
        trend: dict[str, Any] = {
            "value_column": value_name,
            "first": {"label": first[0], "value": _round(first[1])},
            "last": {"label": last[0], "value": _round(last[1])},
            "change": _round(last[1] - first[1]),
        }
        if first[1] != 0:
            trend["change_pct"] = _round((last[1] - first[1]) / abs(first[1]) * 100)
        stats["trend"] = trend
    return stats


# ---------------------------------------------------------------- numbers in text


@dataclass(frozen=True)
class _Number:
    candidates: list[tuple[float, float]]  # (value, tolerance); more than one when ambiguous


def _interpret(token: str) -> list[tuple[float, int]]:
    """Readings of a numeric token as (value, decimals). `1.234` may be 1234 or 1.234."""
    has_dot, has_comma = "." in token, "," in token
    if has_dot and has_comma:
        last = max(token.rfind("."), token.rfind(","))
        thousands = "," if token[last] == "." else "."
        integer = token[:last].replace(thousands, "")
        fraction = token[last + 1 :]
        return [(float(f"{integer}.{fraction}"), len(fraction))]
    if not has_dot and not has_comma:
        return [(float(token), 0)]
    separator = "." if has_dot else ","
    parts = token.split(separator)
    if len(parts) > 2:
        return [(float("".join(parts)), 0)]
    head, tail = parts
    if len(tail) == 3 and 1 <= len(head) <= 3 and head != "0":
        return [(float(head + tail), 0), (float(f"{head}.{tail}"), 3)]
    return [(float(f"{head}.{tail}"), len(tail))]


def _parse(text: str) -> list[_Number]:
    cleaned = _LIST_NUMBER.sub("", text)
    cleaned = _DATE_OR_TIME.sub(" ", cleaned)
    cleaned = _RUPIAH.sub(" ", cleaned)
    found: list[_Number] = []
    for match in _NUMBER.finditer(cleaned):
        token, percent, word = match.group(1), match.group(2), match.group(3)
        scale = _MULTIPLIERS[word.lower()] if word else 1.0
        if not (percent or word) and re.fullmatch(r"\d{4}", token) and 1900 <= int(token) <= 2100:
            continue  # a year
        found.append(
            _Number(
                [(value * scale, 0.5 * 10 ** (-dec) * scale) for value, dec in _interpret(token)]
            )
        )
    return found


def extract_numbers(text: str) -> list[float]:
    """Numbers in `text` (Indonesian or English, `%`, `juta`). Dates and years are skipped."""
    return [number.candidates[0][0] for number in _parse(text)]


def _leaves(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [float(value)]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item)]
    return []


def _references(columns: list[str], rows: list[list[Any]], stats: dict[str, Any]) -> list[float]:
    refs = _leaves(stats)
    for row in rows:
        for cell in row:
            if isinstance(cell, str):  # digits inside labels, such as "Outlet 3"
                refs.extend(c[0] for n in _parse(cell) for c in n.candidates)
            else:
                refs.extend(_leaves(cell))
    return [abs(ref) for ref in refs]


def is_grounded(
    text: str, columns: list[str], rows: list[list[Any]], stats: dict[str, Any]
) -> bool:
    """True when every number in `text` matches a result value or a statistic (sign ignored)."""
    numbers = _parse(text)
    if not numbers:
        return True
    refs = _references(columns, rows, stats)
    return all(
        any(
            abs(abs(value) - ref) <= tolerance + 1e-9
            for value, tolerance in number.candidates
            for ref in refs
        )
        for number in numbers
    )


# ---------------------------------------------------------------- text


def _format(value: float) -> str:
    """Indonesian number format: `1.234.567,5`."""
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", ".")
    swapped = f"{value:,.2f}".replace(",", "x").replace(".", ",").replace("x", ".")
    return swapped.rstrip("0").rstrip(",")


def _cell(value: Any) -> str:
    if value is None:
        return "kosong"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _format(value)
    return _label(value)


def template_insight(columns: list[str], rows: list[list[Any]], stats: dict[str, Any]) -> str:
    """A fixed sentence built from the statistics. Grounded by construction."""
    if not rows:
        return NO_DATA
    if len(rows) == 1:
        parts = [f"{name} = {_cell(value)}" for name, value in zip(columns, rows[0], strict=True)]
        return "; ".join(parts[:6]) + "."
    if "ranking" in stats:
        ranking = stats["ranking"]
        total = stats["columns"][ranking["value_column"]]["sum"]
        return (
            f"{ranking['value_column']} tertinggi pada {ranking['top']['label']} "
            f"({_format(ranking['top']['value'])}), terendah pada {ranking['bottom']['label']} "
            f"({_format(ranking['bottom']['value'])}); {stats['row_count']} baris, "
            f"total {_format(total)}."
        )
    if "trend" in stats:
        trend = stats["trend"]
        text = (
            f"{trend['value_column']} dari {trend['first']['label']} "
            f"({_format(trend['first']['value'])}) menjadi {trend['last']['label']} "
            f"({_format(trend['last']['value'])}), perubahan {_format(trend['change'])}"
        )
        if "change_pct" in trend:
            text += f" ({_format(trend['change_pct'])}%)"
        return text + "."
    return f"Hasil memuat {len(rows)} baris dan {len(columns)} kolom."


def _table_text(columns: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return " ".join("NULL" if value is None else str(value).split())[:MAX_CELL_CHARS]

    lines = [" | ".join(columns)]
    lines.extend(" | ".join(cell(value) for value in row) for row in rows)
    return "\n".join(lines)


async def generate_insight(
    gateway: LLMGateway,
    registry: PromptRegistry,
    *,
    question: str,
    columns: list[str],
    rows: list[list[Any]],
    trace: TraceInfo,
) -> InsightResult:
    stats = compute_stats(columns, rows)
    if not rows:
        return InsightResult(NO_DATA, grounded=True, used_fallback=False)

    shown = rows[:MAX_PROMPT_ROWS]
    note = (
        f"Showing the first {len(shown)} of {len(rows)} rows. STATS cover all {len(rows)} rows.\n"
        if len(rows) > len(shown)
        else ""
    )
    shown_stats = json.loads(json.dumps(stats))
    if "shares" in shown_stats.get("ranking", {}):  # the model sees shares of the rows it sees
        shown_stats["ranking"]["shares"] = shown_stats["ranking"]["shares"][:MAX_PROMPT_ROWS]
    prompt = registry.get("insight")
    user = "\n".join(
        [
            wrap_untrusted_block("question", [{"text": question}]),
            note + wrap_untrusted_block("result", [{"text": _table_text(columns, shown)}]),
            wrap_untrusted_block("stats", [{"text": json.dumps(shown_stats, ensure_ascii=False)}]),
        ]
    )
    messages = [ChatMessage("system", prompt.render()), ChatMessage("user", user)]
    named = replace(trace, prompt_name=prompt.name, prompt_version=prompt.version)
    try:
        reply = (await gateway.chat(messages, named)).content.strip()
    except LLMUnavailableError:
        logger.warning("The model is unavailable; using the template insight", exc_info=True)
        return InsightResult(
            template_insight(columns, rows, stats), grounded=True, used_fallback=True
        )
    if reply and is_grounded(reply, columns, rows, stats):
        return InsightResult(reply, grounded=True, used_fallback=False)
    return InsightResult(template_insight(columns, rows, stats), grounded=False, used_fallback=True)
