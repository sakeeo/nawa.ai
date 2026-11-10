import uuid
from dataclasses import replace

from nawa.knowledge.chunking import estimate_tokens
from nawa.knowledge.context import ELLIPSIS, assemble_context
from tests.knowledge.test_gate import cand


def _c(i: int, chars: int = 40):  # type: ignore[no-untyped-def]
    return replace(cand(0.9, i), text=f"{i}" * chars, chunk_id=uuid.UUID(int=i))


def test_markers_are_sequential_in_order() -> None:
    passages = assemble_context([_c(1), _c(2), _c(3)], max_tokens=1000, final_k=5)
    assert [(p.marker, p.candidate.chunk_id.int) for p in passages] == [(1, 1), (2, 2), (3, 3)]


def test_token_budget_is_respected_and_chunks_are_not_split() -> None:
    chunks = [_c(i, 40) for i in range(1, 6)]  # 10 tokens each
    passages = assemble_context(chunks, max_tokens=25, final_k=5)
    assert len(passages) == 2
    assert sum(estimate_tokens(p.candidate.text) for p in passages) <= 25
    assert all(p.candidate.text in {c.text for c in chunks} for p in passages)


def test_final_k_limits_count() -> None:
    assert len(assemble_context([_c(i) for i in range(1, 6)], max_tokens=1000, final_k=3)) == 3


def test_oversized_first_chunk_is_truncated_not_dropped() -> None:
    passages = assemble_context([_c(1, 4000), _c(2)], max_tokens=100, final_k=5)
    assert len(passages) == 1
    text = passages[0].candidate.text
    assert text.endswith(ELLIPSIS) and estimate_tokens(text) <= 100


def test_exact_duplicates_are_dropped() -> None:
    a, b = _c(1), replace(_c(2), text=_c(1).text)
    passages = assemble_context([a, b, _c(3)], max_tokens=1000, final_k=5)
    assert [p.candidate.chunk_id.int for p in passages] == [1, 3]
    assert [p.marker for p in passages] == [1, 2]


def test_empty_input() -> None:
    assert assemble_context([], max_tokens=100, final_k=5) == []
