import hashlib
import re
from pathlib import Path

import pytest
import yaml

from nawa.knowledge.extract import detect_kind, extract_blocks

DOCS = Path(__file__).resolve().parents[4] / "seed" / "noesantara_docs"
MANIFEST = DOCS / "MANIFEST.yaml"
DENYLIST = ("pt unilever", "nestle", "indofood", "mcdonald", "kfc", "starbucks", "gojek", "grab")
KINDS = {"sop", "policy", "contract", "report", "hr", "injection"}

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="demo documents not generated yet")


def _entries() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["documents"]


def test_manifest_lists_existing_files_with_matching_hashes() -> None:
    for entry in _entries():
        path = DOCS / entry["filename"]
        assert path.is_file(), entry["filename"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["filename"]
        assert entry["kind"] in KINDS
        assert entry["title"] and entry["language"] == "id"


def test_no_unlisted_files() -> None:
    listed = {e["filename"] for e in _entries()} | {"MANIFEST.yaml"}
    assert {p.name for p in DOCS.iterdir()} == listed


def test_document_counts_and_formats() -> None:
    entries = _entries()
    injection = [e for e in entries if e["kind"] == "injection"]
    normal = [e for e in entries if e["kind"] != "injection"]
    assert 28 <= len(normal) <= 34
    assert len(injection) == 2
    assert all(
        e["filename"].startswith("injection-") and e["filename"].endswith(".md") for e in injection
    )
    suffixes = {Path(e["filename"]).suffix for e in entries}
    assert {".docx", ".pdf"} <= suffixes


def test_every_document_is_extractable_and_non_empty() -> None:
    for entry in _entries():
        data = (DOCS / entry["filename"]).read_bytes()
        kind = detect_kind(data, entry["filename"])
        blocks = extract_blocks(data, kind, max_pages=200)
        assert sum(len(b.text) for b in blocks) > 200, entry["filename"]


def test_facts_are_present_for_normal_documents() -> None:
    for entry in _entries():
        if entry["kind"] != "injection":
            assert 3 <= len(entry["facts"]) <= 5, entry["filename"]


def test_no_personal_data_or_real_companies() -> None:
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    phone = re.compile(r"(?:\+62|\b08)\d[\d\s-]{7,}")
    for entry in _entries():
        data = (DOCS / entry["filename"]).read_bytes()
        kind = detect_kind(data, entry["filename"])
        text = "\n".join(b.text for b in extract_blocks(data, kind, max_pages=200))
        assert not email.search(text), entry["filename"]
        assert not phone.search(text), entry["filename"]
        assert not any(name in text.lower() for name in DENYLIST), entry["filename"]


def test_complaint_policy_has_the_demo_story_procedure() -> None:
    entry = next(e for e in _entries() if e["filename"].startswith("kebijakan-komplain-pelanggan"))
    assert "tidak layak" in (DOCS / entry["filename"]).read_text(encoding="utf-8").lower()


def test_injection_documents_contain_an_override_attempt() -> None:
    for entry in _entries():
        if entry["kind"] == "injection":
            text = (DOCS / entry["filename"]).read_text(encoding="utf-8").lower()
            assert "abaikan semua instruksi" in text
