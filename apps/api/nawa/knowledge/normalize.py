import re
import unicodedata
from dataclasses import replace

from nawa.knowledge.extract import Block

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
_REPEAT_PAGES = 3


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


_MAX_FOOTER_CHARS = 40


def _key(line: str) -> str:
    """Digits are ignored only for short lines, so page numbers match but prose does not."""
    key = line.strip().lower()
    return re.sub(r"\d+", "#", key) if len(key) <= _MAX_FOOTER_CHARS else key


def drop_repeated_lines(blocks: list[Block]) -> list[Block]:
    """Remove lines that repeat (digits ignored) on at least 3 pages: headers and footers."""
    pages_by_key: dict[str, set[int]] = {}
    for block in blocks:
        if block.page is None:
            continue
        for line in block.text.split("\n"):
            if line.strip():
                pages_by_key.setdefault(_key(line), set()).add(block.page)
    repeated = {k for k, pages in pages_by_key.items() if len(pages) >= _REPEAT_PAGES}
    if not repeated:
        return blocks
    kept: list[Block] = []
    for block in blocks:
        if block.page is None:
            kept.append(block)
            continue
        lines = [ln for ln in block.text.split("\n") if _key(ln) not in repeated]
        text = "\n".join(lines).strip()
        if text:
            heading = text if block.level is not None else None
            kept.append(replace(block, text=text, heading=heading))
    return kept


def normalize_blocks(blocks: list[Block]) -> list[Block]:
    """Drop headers and footers, then clean the text of every block; empty blocks vanish."""
    result: list[Block] = []
    for block in drop_repeated_lines(blocks):
        text = normalize_text(block.text)
        if block.page is not None and block.level is None:
            text = re.sub(r"\s*\n\s*", " ", text)  # undo PDF line wrapping
        if text:
            result.append(
                replace(block, text=text, heading=text if block.level is not None else None)
            )
    return result
