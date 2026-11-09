from pathlib import Path

import pytest
import yaml

from nawa.evaluation.dataset import DatasetError, load_golden

ROOT = Path(__file__).resolve().parents[4]
REAL_GOLDEN = ROOT / "evals" / "golden.yaml"
REAL_MANIFEST = ROOT / "seed" / "noesantara_docs" / "MANIFEST.yaml"

MANIFEST = {
    "documents": [
        {"filename": "a.md", "kind": "sop", "facts": ["f0", "f1"]},
        {"filename": "trap.md", "kind": "injection", "facts": []},
    ]
}


def _write(tmp_path: Path, items: list[dict]) -> tuple[Path, Path]:
    golden, manifest = tmp_path / "g.yaml", tmp_path / "m.yaml"
    golden.write_text(yaml.safe_dump({"items": items}), encoding="utf-8")
    manifest.write_text(yaml.safe_dump(MANIFEST), encoding="utf-8")
    return golden, manifest


def _a(i: str = "A1", **kw: object) -> dict:
    return {
        "id": i,
        "kind": "answerable",
        "question": "q?",
        "reference_answer": "r",
        "source_files": ["a.md"],
        "source_facts": ["a.md#1"],
        **kw,
    }


def test_real_dataset_validates_against_the_real_manifest() -> None:
    items = load_golden(REAL_GOLDEN, REAL_MANIFEST)
    kinds = [i.kind for i in items]
    assert (kinds.count("answerable"), kinds.count("unanswerable"), kinds.count("injection")) == (
        60,
        10,
        5,
    )


def test_valid_small_dataset_loads(tmp_path: Path) -> None:
    golden, manifest = _write(
        tmp_path,
        [
            _a(),
            {"id": "U1", "kind": "unanswerable", "question": "x?"},
            {
                "id": "I1",
                "kind": "injection",
                "question": "q",
                "trap_file": "trap.md",
                "forbidden": ["X"],
            },
        ],
    )
    items = load_golden(golden, manifest, expected_counts=None)
    assert [i.id for i in items] == ["A1", "U1", "I1"]


def test_missing_source_file_names_the_item(tmp_path: Path) -> None:
    golden, manifest = _write(tmp_path, [_a(source_files=["ghost.md"])])
    with pytest.raises(DatasetError, match="A1.*ghost.md"):
        load_golden(golden, manifest, expected_counts=None)


def test_unknown_fact_is_rejected(tmp_path: Path) -> None:
    golden, manifest = _write(tmp_path, [_a(source_facts=["a.md#9"])])
    with pytest.raises(DatasetError, match="A1.*a.md#9"):
        load_golden(golden, manifest, expected_counts=None)


def test_duplicate_ids_and_wrong_counts_are_rejected(tmp_path: Path) -> None:
    golden, manifest = _write(tmp_path, [_a(), _a()])
    with pytest.raises(DatasetError, match="duplicate"):
        load_golden(golden, manifest, expected_counts=None)
    golden, manifest = _write(tmp_path, [_a()])
    with pytest.raises(DatasetError, match="expected 60 answerable"):
        load_golden(golden, manifest)


def test_injection_trap_must_be_an_injection_document(tmp_path: Path) -> None:
    bad = {
        "id": "I1",
        "kind": "injection",
        "question": "q",
        "trap_file": "a.md",
        "forbidden": ["X"],
    }
    golden, manifest = _write(tmp_path, [bad])
    with pytest.raises(DatasetError, match="I1.*injection document"):
        load_golden(golden, manifest, expected_counts=None)


def test_unanswerable_questions_are_absent_from_the_documents() -> None:
    """The ten 'unanswerable' items must be genuinely absent: their key terms never occur."""
    from nawa.knowledge.extract import detect_kind, extract_blocks

    docs = REAL_MANIFEST.parent
    corpus = ""
    for path in docs.iterdir():
        if path.name == "MANIFEST.yaml":
            continue
        data = path.read_bytes()
        corpus += "\n".join(
            b.text for b in extract_blocks(data, detect_kind(data, path.name), max_pages=200)
        ).lower()
    absent = [
        "gaji",
        "qris",
        "direktur",
        "parkir",
        "banjir",
        "reservasi",
        "bonus",
        "asuransi",
        "bpjs",
        "franchise",
    ]
    assert [t for t in absent if t in corpus] == []
