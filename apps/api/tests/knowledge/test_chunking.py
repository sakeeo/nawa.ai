import random
import re

import pytest

from nawa.knowledge.chunking import (
    FixedChunker,
    HeadingChunker,
    estimate_tokens,
    get_chunker,
)
from nawa.knowledge.extract import Block


def h(text: str, level: int, page: int | None = 1) -> Block:
    return Block(text=text, page=page, heading=text, level=level)


def p(text: str, page: int | None = 1) -> Block:
    return Block(text=text, page=page, heading=None, level=None)


def sentences(n: int, tag: str) -> str:
    return " ".join(
        f"Kalimat {tag} nomor {i} menjelaskan prosedur dapur dengan jelas." for i in range(n)
    )


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_short_section_stays_whole_with_path_prefix() -> None:
    blocks = [
        h("Bab 2", 1),
        h("Penerimaan Daging", 2),
        p("Periksa suhu."),
        p("Tolak jika di atas 5 derajat."),
    ]
    chunks = HeadingChunker().chunk(blocks)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.section_path == "Bab 2 > Penerimaan Daging"
    assert c.heading == "Penerimaan Daging"
    assert c.text == "Bab 2 > Penerimaan Daging\n\nPeriksa suhu.\n\nTolak jika di atas 5 derajat."


def test_long_section_splits_with_overlap_and_respects_max() -> None:
    chunker = HeadingChunker(target_tokens=100, overlap_tokens=30, max_tokens=150)
    blocks = [h("Panjang", 1)] + [p(sentences(6, str(i))) for i in range(8)]
    chunks = chunker.chunk(blocks)
    assert len(chunks) > 2
    assert all(estimate_tokens(c.text) <= 150 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        prev_sents = re.split(r"(?<=[.!?])\s+", prev.text.split("\n\n", 1)[1].strip())
        assert prev_sents[-1] in nxt.text


def test_ordinals_contiguous_and_no_empty_chunks() -> None:
    blocks = [h("A", 1), p(sentences(40, "a")), h("B", 1), p("Pendek."), h("C", 1), p("Kecil.")]
    chunks = HeadingChunker(target_tokens=100, overlap_tokens=20, max_tokens=150).chunk(blocks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(c.text.strip() and c.token_count > 0 for c in chunks)


def test_page_is_page_of_first_block() -> None:
    blocks = [h("A", 1, 3), p("x " * 10, 3), p("y " * 10, 4)]
    chunks = HeadingChunker().chunk(blocks)
    assert chunks[0].page == 3


def test_tiny_trailing_section_merges_into_previous_with_same_parent() -> None:
    blocks = [
        h("Induk", 1),
        h("Besar", 2),
        p(sentences(30, "b")),
        h("Kecil", 2),
        p("Catatan singkat."),
    ]
    chunker = HeadingChunker(target_tokens=100, overlap_tokens=20, max_tokens=150)
    chunks = chunker.chunk(blocks)
    assert "Catatan singkat." in chunks[-1].text
    assert all("Kecil" not in c.section_path for c in chunks)


def test_blocks_before_first_heading_have_empty_path() -> None:
    chunks = HeadingChunker().chunk([p("Pembuka tanpa judul."), h("Judul", 1), p("Isi.")])
    assert chunks[0].section_path == ""
    assert chunks[0].text == "Pembuka tanpa judul."


def test_fixed_chunker_windows_within_ten_percent_and_ignores_headings() -> None:
    blocks = [h("Judul", 1)] + [p(sentences(10, str(i))) for i in range(10)]
    chunks = FixedChunker(size_tokens=200, overlap_tokens=30).chunk(blocks)
    assert len(chunks) > 3
    for c in chunks[:-1]:
        assert 180 <= c.token_count <= 220
    assert all(c.section_path == "" and c.heading is None for c in chunks)


def test_chunkers_are_deterministic() -> None:
    blocks = [h("A", 1), p(sentences(30, "z")), h("B", 1), p(sentences(5, "q"))]
    for name in ("heading", "fixed"):
        chunker = get_chunker(name)
        assert chunker.chunk(blocks) == chunker.chunk(blocks)


def test_get_chunker_unknown_name() -> None:
    with pytest.raises(ValueError):
        get_chunker("nope")


def test_oversized_single_sentence_is_hard_split() -> None:
    word_soup = " ".join(["kata"] * 600)
    chunks = HeadingChunker(target_tokens=100, overlap_tokens=10, max_tokens=150).chunk(
        [h("T", 1), p(word_soup)]
    )
    assert all(estimate_tokens(c.text) <= 150 for c in chunks)


@pytest.mark.parametrize("seed", range(20))
def test_no_sentence_is_lost(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311  (deterministic test data)
    blocks: list[Block] = []
    expected: list[str] = []
    for s in range(rng.randint(1, 6)):
        blocks.append(h(f"Bagian {s}", rng.randint(1, 3), page=s + 1))
        for para in range(rng.randint(0, 4)):
            sents = [
                f"Fakta {seed}-{s}-{para}-{k} adalah {'x' * rng.randint(3, 120)}."
                for k in range(rng.randint(1, 12))
            ]
            expected.extend(sents)
            blocks.append(p(" ".join(sents), page=s + 1))
    for chunker in (
        HeadingChunker(target_tokens=80, overlap_tokens=20, max_tokens=120),
        FixedChunker(size_tokens=80, overlap_tokens=20),
    ):
        joined = "\n".join(c.text for c in chunker.chunk(blocks))
        for sentence in expected:
            assert sentence in joined
