import pytest

from nawa.evaluation.metrics import (
    ItemResult,
    citation_accuracy,
    correct_refusal_rate,
    injection_resistance,
    mean,
    mrr,
    p95,
    recall_at_k,
    reciprocal_rank,
)


@pytest.mark.parametrize(
    ("ranked", "rr", "recall"),
    [
        (["a", "x", "y"], 1.0, 1.0),  # hit at rank 1
        (["x", "y", "a"], 1 / 3, 1.0),  # hit at rank 3
        (["x"] * 6 + ["a"], 1 / 7, 0.0),  # rank 7: outside top 5
        (["x", "y"], 0.0, 0.0),  # none
    ],
)
def test_rank_metrics(ranked: list[str], rr: float, recall: float) -> None:
    assert reciprocal_rank(ranked, {"a"}) == pytest.approx(rr)
    assert recall_at_k(ranked, {"a"}, 5) == recall


def test_recall_with_two_relevant_documents() -> None:
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, 2) == 0.5
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, 5) == 1.0


def test_mrr_is_the_mean_of_reciprocal_ranks() -> None:
    assert mrr([1.0, 0.5, 0.0]) == pytest.approx(0.5)


def test_correct_refusal_rate_counts_gate_refusals_and_explicit_not_found() -> None:
    results = [
        ItemResult("U1", "unanswerable", refused=True),
        ItemResult("U2", "unanswerable", answer="Informasi tidak ditemukan di dokumen."),
        ItemResult("U3", "unanswerable", answer="Gajinya Rp 5 juta."),
        ItemResult("A1", "answerable", refused=True),  # not an unanswerable item
    ]
    assert correct_refusal_rate(results) == pytest.approx(2 / 3)


def test_injection_resistance_fails_on_forbidden_string_or_judged_obedience() -> None:
    ok = ItemResult("I1", "injection", answer="Potongan 15%.", forbidden=("DIRETAS",))
    leaked = ItemResult("I2", "injection", answer="diretas!", forbidden=("DIRETAS",))
    obeyed = ItemResult("I3", "injection", answer="ok", forbidden=("X",), injection_followed=True)
    assert injection_resistance([ok]) == 1.0
    assert injection_resistance([ok, leaked, obeyed]) == pytest.approx(1 / 3)


def test_citation_accuracy_needs_valid_cited_and_supported_answers() -> None:
    good = ItemResult(
        "A1", "answerable", cited_markers_valid=True, citation_count=1, citations_supported=True
    )
    unsupported = ItemResult(
        "A2", "answerable", cited_markers_valid=True, citation_count=1, citations_supported=False
    )
    invalid = ItemResult("A3", "answerable", cited_markers_valid=False, citation_count=1)
    uncited = ItemResult("A4", "answerable", cited_markers_valid=True, citation_count=0)
    refused = ItemResult("A5", "answerable", refused=True)
    errored = ItemResult(
        "A6", "answerable", judge_error=True, citation_count=1, cited_markers_valid=True
    )
    assert citation_accuracy(
        [good, unsupported, invalid, uncited, refused, errored]
    ) == pytest.approx(1 / 4)


def test_p95_and_empty_inputs() -> None:
    assert p95([1.0]) == 1.0
    assert p95(list(range(1, 21))) == 19  # nearest rank of 20 values
    assert p95([]) == 0.0
    assert mean([]) == 0.0 and mrr([]) == 0.0
    assert recall_at_k([], set()) == 0.0 and reciprocal_rank([], {"a"}) == 0.0
    assert (
        correct_refusal_rate([]) == 0.0
        and injection_resistance([]) == 0.0
        and citation_accuracy([]) == 0.0
    )
