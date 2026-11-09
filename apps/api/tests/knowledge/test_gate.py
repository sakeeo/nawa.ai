import uuid

from nawa.knowledge.gate import relevance_gate
from nawa.knowledge.retrieval import Candidate


def cand(similarity: float, i: int = 1) -> Candidate:
    return Candidate(
        chunk_id=uuid.UUID(int=i),
        document_id=uuid.UUID(int=99),
        filename="a.md",
        page=None,
        section_path="",
        heading=None,
        text=f"text {i}",
        similarity=similarity,
        vector_rank=i,
        keyword_rank=None,
        rrf_score=0.01,
    )


def test_no_candidates_refuses() -> None:
    d = relevance_gate([], min_similarity=0.35)
    assert (d.answerable, d.reason, d.best_similarity) == (False, "no_candidates", None)


def test_below_threshold_refuses() -> None:
    d = relevance_gate([cand(0.2), cand(0.3, 2)], min_similarity=0.35)
    assert (d.answerable, d.reason) == (False, "below_threshold")
    assert d.best_similarity == 0.3


def test_equal_to_threshold_is_answerable() -> None:
    d = relevance_gate([cand(0.35)], min_similarity=0.35)
    assert (d.answerable, d.reason) == (True, "ok")


def test_uses_the_maximum_not_the_first() -> None:
    d = relevance_gate([cand(0.1), cand(0.9, 2), cand(0.2, 3)], min_similarity=0.35)
    assert d.answerable and d.best_similarity == 0.9
