from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

COUNTS = {"answerable": 60, "unanswerable": 10, "injection": 5}


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class GoldenItem:
    id: str
    kind: Literal["answerable", "unanswerable", "injection"]
    question: str
    reference_answer: str | None = None
    source_files: tuple[str, ...] = ()
    source_facts: tuple[str, ...] = ()
    trap_file: str | None = None
    forbidden: tuple[str, ...] = ()


def _fact_exists(manifest: dict[str, dict[str, Any]], fact_id: str) -> bool:
    filename, _, index = fact_id.rpartition("#")
    entry = manifest.get(filename)
    return entry is not None and index.isdigit() and int(index) < len(entry["facts"])


def load_golden(
    path: Path, manifest_path: Path, *, expected_counts: dict[str, int] | None = COUNTS
) -> list[GoldenItem]:
    """Load and validate the golden dataset against the locked document manifest.

    Fact ids are `<filename>#<index>` into that file's `facts` list in the manifest.
    """
    manifest = {
        e["filename"]: e
        for e in yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["documents"]
    }
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["items"]
    items: list[GoldenItem] = []
    seen: set[str] = set()
    for row in raw:
        item_id = str(row.get("id", ""))
        if not item_id or item_id in seen:
            raise DatasetError(f"duplicate or missing id: {item_id!r}")
        seen.add(item_id)
        kind = row.get("kind")
        if kind not in COUNTS:
            raise DatasetError(f"{item_id}: unknown kind {kind!r}")
        if not str(row.get("question", "")).strip():
            raise DatasetError(f"{item_id}: empty question")
        item = GoldenItem(
            id=item_id,
            kind=kind,
            question=row["question"],
            reference_answer=row.get("reference_answer"),
            source_files=tuple(row.get("source_files", ())),
            source_facts=tuple(row.get("source_facts", ())),
            trap_file=row.get("trap_file"),
            forbidden=tuple(row.get("forbidden", ())),
        )
        if kind == "answerable":
            if not item.reference_answer or not item.source_files:
                raise DatasetError(f"{item_id}: answerable items need a reference and sources")
            for filename in item.source_files:
                if filename not in manifest:
                    raise DatasetError(
                        f"{item_id}: source file {filename!r} is not in the manifest"
                    )
            for fact in item.source_facts:
                if not _fact_exists(manifest, fact):
                    raise DatasetError(f"{item_id}: fact {fact!r} does not exist in the manifest")
        if kind == "injection":
            if item.trap_file not in manifest or manifest[item.trap_file]["kind"] != "injection":
                raise DatasetError(
                    f"{item_id}: trap_file {item.trap_file!r} is not an injection document"
                )
            if not item.forbidden:
                raise DatasetError(f"{item_id}: injection items need forbidden strings")
        items.append(item)
    if expected_counts is not None:
        for kind, expected in expected_counts.items():
            actual = sum(1 for i in items if i.kind == kind)
            if actual != expected:
                raise DatasetError(f"expected {expected} {kind} items, found {actual}")
    return items
