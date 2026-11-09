import io

import pytest
from docx import Document as DocxDocument

from nawa.knowledge.extract import (
    DocumentTooLargeError,
    UnsupportedDocumentError,
    detect_kind,
    extract_blocks,
)
from nawa.knowledge.normalize import drop_repeated_lines, normalize_blocks, normalize_text
from tests.knowledge.pdfs import make_pdf


def make_docx() -> bytes:
    doc = DocxDocument()
    doc.add_heading("Kebijakan Refund", level=1)
    doc.add_paragraph("Refund diproses dalam tujuh hari.")
    doc.add_heading("Syarat", level=2)
    doc.add_paragraph("Struk wajib dibawa.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Jenis"
    table.cell(0, 1).text = "Batas"
    table.cell(1, 0).text = "Makanan"
    table.cell(1, 1).text = "24 jam"
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_detect_kind_uses_content_not_extension() -> None:
    assert detect_kind(make_pdf([["Halo"]]), "laporan.txt") == "pdf"
    assert detect_kind(make_docx(), "memo.pdf") == "docx"
    assert detect_kind(b"# Judul\n\nIsi", "catatan.md") == "md"
    assert detect_kind(b"Teks biasa", "catatan.txt") == "txt"


def test_text_pretending_to_be_pdf_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError):
        detect_kind(b"just some text", "fake.pdf")
    with pytest.raises(UnsupportedDocumentError):
        detect_kind(b"just some text", "fake.docx")


@pytest.mark.parametrize("data", [b"", b"\x00\x01\x02\xff\xfe binary", b"PK\x03\x04 not docx"])
def test_empty_or_binary_is_rejected(data: bytes) -> None:
    with pytest.raises(UnsupportedDocumentError):
        detect_kind(data, "x.txt")


def test_unknown_text_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError):
        detect_kind(b"a,b\n1,2", "data.csv")


def test_markdown_headings_become_levels() -> None:
    blocks = extract_blocks(b"# Satu\n\nIsi satu.\n\n## Dua\n\nIsi dua.", "md", max_pages=10)
    assert [(b.level, b.text) for b in blocks] == [
        (1, "Satu"),
        (None, "Isi satu."),
        (2, "Dua"),
        (None, "Isi dua."),
    ]
    assert blocks[0].heading == "Satu"
    assert blocks[1].heading is None


def test_txt_heading_heuristics() -> None:
    text = "PROSEDUR KOMPLAIN\n\nCatat keluhan pelanggan.\n\nLangkah penanganan:\n\nMinta maaf."
    blocks = extract_blocks(text.encode(), "txt", max_pages=10)
    assert [b.level for b in blocks] == [1, None, 1, None]


def test_docx_headings_and_tables() -> None:
    blocks = extract_blocks(make_docx(), "docx", max_pages=10)
    assert [(b.level, b.text) for b in blocks[:4]] == [
        (1, "Kebijakan Refund"),
        (None, "Refund diproses dalam tujuh hari."),
        (2, "Syarat"),
        (None, "Struk wajib dibawa."),
    ]
    assert [b.text for b in blocks[4:]] == ["Jenis | Batas", "Makanan | 24 jam"]
    assert all(b.level is None for b in blocks[4:])


def test_pdf_pages_and_heading_heuristic() -> None:
    pdf = make_pdf(
        [
            ["PENERIMAAN BAHAN", "Periksa suhu daging saat tiba."],
            ["Simpan di freezer segera."],
        ]
    )
    blocks = extract_blocks(pdf, "pdf", max_pages=10)
    assert blocks[0].level == 1 and blocks[0].text == "PENERIMAAN BAHAN"
    assert blocks[0].page == 1
    assert blocks[-1].page == 2 and "freezer" in blocks[-1].text


def test_pdf_over_page_limit_is_rejected() -> None:
    pdf = make_pdf([["satu"], ["dua"], ["tiga"]])
    with pytest.raises(DocumentTooLargeError):
        extract_blocks(pdf, "pdf", max_pages=2)


def test_normalize_text_cleans_whitespace_and_zero_width() -> None:
    raw = "Ha​lo   dunia\t\tx\r\n\r\n\r\n\r\nBaris  baru "
    assert normalize_text(raw) == "Halo dunia x\n\nBaris baru"
    assert normalize_text("é") == "é"


def test_repeated_header_and_footer_lines_are_dropped() -> None:
    pdf = make_pdf(
        [
            ["PT Noesantara Kuliner", body, f"Halaman {n} dari 4"]
            for n, body in enumerate(
                [
                    "Isi pertama membahas suhu penyimpanan daging beku.",
                    "Isi kedua membahas kebersihan area dapur utama.",
                    "Isi ketiga membahas penanganan keluhan pelanggan.",
                    "Isi keempat membahas prosedur pengembalian dana.",
                ],
                start=1,
            )
        ]
    )
    blocks = normalize_blocks(extract_blocks(pdf, "pdf", max_pages=10))
    joined = "\n".join(b.text for b in blocks)
    assert "PT Noesantara Kuliner" not in joined
    assert "Halaman" not in joined
    assert "Isi kedua membahas" in joined


def test_lines_on_fewer_than_three_pages_are_kept() -> None:
    pdf = make_pdf([["Judul Repetitif", "a"], ["Judul Repetitif", "b"]])
    blocks = drop_repeated_lines(extract_blocks(pdf, "pdf", max_pages=10))
    assert any("Judul Repetitif" in b.text for b in blocks)
