import math
import re
from dataclasses import dataclass
from typing import Protocol

from nawa.knowledge.extract import Block

PATH_SEPARATOR = " > "
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str
    page: int | None
    section_path: str
    heading: str | None
    token_count: int


class Chunker(Protocol):
    def chunk(self, blocks: list[Block]) -> list[ChunkDraft]: ...


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


@dataclass(frozen=True)
class _Unit:
    """A sentence (or a hard-split piece of one) with its page and paragraph position."""

    text: str
    page: int | None
    para_start: bool

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def _hard_split(text: str, max_tokens: int) -> list[str]:
    limit = max(max_tokens * 4, 1)
    words = text.split(" ")
    pieces: list[str] = []
    current = ""
    for word in words:
        while len(word) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:limit])
            word = word[limit:]
        candidate = f"{current} {word}" if current else word
        if len(candidate) > limit and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _units(blocks: list[Block], max_unit_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    for block in blocks:
        first = True
        for sentence in _SENTENCE_END.split(block.text.strip()):
            sentence = sentence.strip()
            if not sentence:
                continue
            pieces = (
                [sentence]
                if estimate_tokens(sentence) <= max_unit_tokens
                else _hard_split(sentence, max_unit_tokens)
            )
            for piece in pieces:
                units.append(_Unit(piece, block.page, first))
                first = False
    return units


def _join(units: list[_Unit]) -> str:
    out: list[str] = []
    for i, unit in enumerate(units):
        if i:
            out.append("\n\n" if unit.para_start else " ")
        out.append(unit.text)
    return "".join(out)


def _windows(units: list[_Unit], target: int, overlap: int) -> list[list[_Unit]]:
    """Greedy windows near `target` tokens; each starts with up to `overlap` tokens of tail."""
    windows: list[list[_Unit]] = []
    i = 0
    n = len(units)
    while i < n:
        j = i
        used = 0
        while j < n and (j == i or used + units[j].tokens <= target):
            used += units[j].tokens
            j += 1
        windows.append(units[i:j])
        if j >= n:
            break
        k = j
        carried = 0
        while k > i + 1 and carried + units[k - 1].tokens <= overlap:
            carried += units[k - 1].tokens
            k -= 1
        i = k
    return windows


def _draft(ordinal: int, text: str, page: int | None, path: str, heading: str | None) -> ChunkDraft:
    return ChunkDraft(ordinal, text, page, path, heading, estimate_tokens(text))


@dataclass
class _Section:
    path: str
    heading: str | None
    blocks: list[Block]


def _sections(blocks: list[Block]) -> list[_Section]:
    stack: list[tuple[int, str]] = []
    sections: list[_Section] = [_Section("", None, [])]
    for block in blocks:
        if block.level is not None:
            while stack and stack[-1][0] >= block.level:
                stack.pop()
            stack.append((block.level, block.text))
            sections.append(_Section(PATH_SEPARATOR.join(t for _, t in stack), block.text, []))
        else:
            sections[-1].blocks.append(block)
    return [s for s in sections if s.blocks]


def _parent(path: str) -> str:
    return path.rsplit(PATH_SEPARATOR, 1)[0] if PATH_SEPARATOR in path else ""


class HeadingChunker:
    def __init__(
        self,
        target_tokens: int = 400,
        overlap_tokens: int = 50,
        max_tokens: int = 600,
        min_tokens: int = 60,
    ) -> None:
        if not 0 < target_tokens < max_tokens:
            raise ValueError("target_tokens must be positive and below max_tokens")
        self.target_tokens = target_tokens
        self.overlap_tokens = overlap_tokens
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens

    def _prefix(self, path: str) -> str:
        if not path:
            return ""
        room = (self.max_tokens - self.target_tokens) * 4 - 8
        shown = path if len(path) <= room else "…" + path[-(room - 1) :]
        return f"{shown}\n\n"

    def chunk(self, blocks: list[Block]) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for section in _sections(blocks):
            prefix = self._prefix(section.path)
            body_budget = self.target_tokens - estimate_tokens(prefix)
            units = _units(section.blocks, max(body_budget, 1))
            if not units:
                continue
            whole = prefix + _join(units)
            if estimate_tokens(whole) <= self.max_tokens:
                if (
                    estimate_tokens(_join(units)) < self.min_tokens
                    and drafts
                    and self._can_merge(drafts[-1], section, whole)
                ):
                    prev = drafts[-1]
                    merged = f"{prev.text}\n\n{section.heading or ''}\n{_join(units)}".rstrip()
                    drafts[-1] = _draft(0, merged, prev.page, prev.section_path, prev.heading)
                    continue
                drafts.append(_draft(0, whole, units[0].page, section.path, section.heading))
                continue
            for window in _windows(units, max(body_budget, 1), self.overlap_tokens):
                drafts.append(
                    _draft(0, prefix + _join(window), window[0].page, section.path, section.heading)
                )
        return [
            ChunkDraft(i, d.text, d.page, d.section_path, d.heading, d.token_count)
            for i, d in enumerate(drafts)
        ]

    def _can_merge(self, prev: ChunkDraft, section: _Section, whole: str) -> bool:
        related = _parent(prev.section_path) == _parent(section.path) or section.path.startswith(
            prev.section_path + PATH_SEPARATOR
        )
        return (
            bool(prev.section_path)
            and related
            and estimate_tokens(prev.text) + estimate_tokens(whole) <= self.max_tokens
        )


class FixedChunker:
    def __init__(self, size_tokens: int = 512, overlap_tokens: int = 50) -> None:
        self.size_tokens = size_tokens
        self.overlap_tokens = overlap_tokens

    def chunk(self, blocks: list[Block]) -> list[ChunkDraft]:
        units = _units(blocks, self.size_tokens)
        windows = _windows(units, self.size_tokens, self.overlap_tokens)
        return [_draft(i, _join(w), w[0].page, "", None) for i, w in enumerate(windows)]


def get_chunker(name: str) -> Chunker:
    if name == "heading":
        return HeadingChunker()
    if name == "fixed":
        return FixedChunker()
    raise ValueError(f"Unknown chunker: {name}")
