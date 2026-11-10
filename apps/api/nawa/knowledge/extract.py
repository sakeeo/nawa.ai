import io
import re
from dataclasses import dataclass
from typing import Literal

import filetype  # type: ignore[import-untyped]
from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PyPdfError

Kind = Literal["pdf", "docx", "txt", "md"]

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_HEADING_CHARS = 80
_PDF_HEADING_CHARS = 60
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")


@dataclass(frozen=True)
class Block:
    """A paragraph, list item or table row. A heading block has `level` set."""

    text: str
    page: int | None
    heading: str | None
    level: int | None


class UnsupportedDocumentError(ValueError):
    pass


class DocumentTooLargeError(ValueError):
    pass


def detect_kind(data: bytes, filename: str) -> Kind:
    """Decide the document kind from its bytes. The extension only splits md from txt."""
    if not data:
        raise UnsupportedDocumentError("The file is empty.")
    lowered = filename.lower()
    guessed = filetype.guess(data)
    mime = guessed.mime if guessed is not None else None
    if mime == PDF_MIME:
        return "pdf"
    if mime == DOCX_MIME:
        return "docx"
    if mime is not None or lowered.endswith((".pdf", ".docx")):
        raise UnsupportedDocumentError("The file content does not match a supported type.")
    if b"\x00" in data:
        raise UnsupportedDocumentError("Binary files are not supported.")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedDocumentError("Text files must be UTF-8.") from exc
    if lowered.endswith((".md", ".markdown")):
        return "md"
    if lowered.endswith(".txt"):
        return "txt"
    raise UnsupportedDocumentError("Supported types: PDF, DOCX, TXT, MD.")


def extract_blocks(data: bytes, kind: str, *, max_pages: int) -> list[Block]:
    if kind == "pdf":
        return _extract_pdf(data, max_pages)
    if kind == "docx":
        return _extract_docx(data)
    if kind == "md":
        return _extract_markdown(data.decode("utf-8"))
    if kind == "txt":
        return _extract_txt(data.decode("utf-8"))
    raise UnsupportedDocumentError(f"Unknown document kind: {kind}")


def _heading(text: str, level: int, page: int | None = None) -> Block:
    return Block(text=text, page=page, heading=text, level=level)


def _paragraph(text: str, page: int | None = None) -> Block:
    return Block(text=text, page=page, heading=None, level=None)


def _paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    return [p.strip() for p in parts if p.strip()]


def _extract_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            joined = "\n".join(buffer).strip()
            if joined:
                blocks.append(_paragraph(joined))
            buffer.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        match = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if match:
            flush()
            if match.group(2):
                blocks.append(_heading(match.group(2), len(match.group(1))))
        elif not line.strip():
            flush()
        else:
            buffer.append(line)
    flush()
    return blocks


def _looks_like_txt_heading(paragraph: str) -> bool:
    if "\n" in paragraph or len(paragraph) >= MAX_HEADING_CHARS:
        return False
    letters = [c for c in paragraph if c.isalpha()]
    return paragraph.endswith(":") or (bool(letters) and paragraph.isupper())


def _extract_txt(text: str) -> list[Block]:
    return [
        _heading(p.rstrip(":").strip(), 1) if _looks_like_txt_heading(p) else _paragraph(p)
        for p in _paragraphs(text)
    ]


def _extract_docx(data: bytes) -> list[Block]:
    try:
        document = DocxDocument(io.BytesIO(data))
    except Exception as exc:  # python-docx raises many types for corrupt packages
        raise UnsupportedDocumentError("The DOCX file could not be read.") from exc
    blocks: list[Block] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            level = _docx_level(style)
            blocks.append(_heading(text, level) if level else _paragraph(text))
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                line = " | ".join(c for c in cells if c)
                if line:
                    blocks.append(_paragraph(line))
    return blocks


def _docx_level(style_name: str) -> int | None:
    match = re.fullmatch(r"Heading (\d)", style_name)
    if match:
        return int(match.group(1))
    return 1 if style_name == "Title" else None


def _pdf_heading_level(line: str) -> int | None:
    """Weak heuristics: short lines without terminal punctuation that look like titles."""
    if len(line) > _PDF_HEADING_CHARS or line.endswith((".", ",", ";")):
        return None
    numbered = _NUMBERED.match(line)
    if numbered:
        return numbered.group(1).count(".") + 1
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 3 and line.isupper():
        return 1
    return None


def _extract_pdf(data: bytes, max_pages: int) -> list[Block]:
    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except (PyPdfError, ValueError, OSError, KeyError) as exc:
        raise UnsupportedDocumentError("The PDF file could not be read.") from exc
    if page_count > max_pages:
        raise DocumentTooLargeError(f"The PDF has {page_count} pages; the limit is {max_pages}.")
    blocks: list[Block] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except (PyPdfError, ValueError, KeyError) as exc:
            raise UnsupportedDocumentError(f"Page {number} could not be read.") from exc
        buffer: list[str] = []

        def flush(page_number: int = number, buffer: list[str] = buffer) -> None:
            if buffer:
                blocks.append(_paragraph("\n".join(buffer), page_number))
                buffer.clear()

        for raw in text.replace("\r\n", "\n").split("\n"):
            line = raw.strip()
            if not line:
                flush()
                continue
            level = _pdf_heading_level(line)
            if level is not None:
                flush()
                blocks.append(_heading(line, level, number))
            else:
                buffer.append(line)
        flush()
    return blocks
