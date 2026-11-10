import uuid

import pytest

from nawa.knowledge.retrieval import build_keyword_query, rrf_fuse

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


def test_chunk_in_both_lists_outranks_chunk_in_one() -> None:
    fused = rrf_fuse([A, B], [C, B])
    assert [f[0] for f in fused][0] == B


def test_worked_example_with_k_60() -> None:
    fused = {f[0]: f for f in rrf_fuse([A, B, C], [B, D], k=60)}
    assert fused[A][1] == pytest.approx(1 / 61)
    assert fused[B][1] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[C][1] == pytest.approx(1 / 63)
    assert fused[D][1] == pytest.approx(1 / 62)
    assert (fused[B][2], fused[B][3]) == (2, 1)
    assert (fused[A][2], fused[A][3]) == (1, None)
    assert (fused[D][2], fused[D][3]) == (None, 2)


def test_empty_inputs() -> None:
    assert rrf_fuse([], []) == []
    assert [f[0] for f in rrf_fuse([A], [])] == [A]


def test_ties_are_deterministic_by_better_rank_then_id() -> None:
    # A is rank 1 in vector only, C is rank 1 in keyword only: equal score, equal best rank.
    fused = rrf_fuse([A, B], [C, D])
    assert [f[0] for f in fused] == [A, C, B, D]
    assert fused == rrf_fuse([A, B], [C, D])


def test_duplicate_ids_in_one_list_count_once_at_first_rank() -> None:
    fused = {f[0]: f for f in rrf_fuse([A, A, B], [])}
    assert fused[A][1] == pytest.approx(1 / 61)
    assert fused[B][1] == pytest.approx(1 / 62)


def test_rank_beyond_list_length_is_just_absent() -> None:
    fused = rrf_fuse([A], [B], k=0)
    assert {f[0]: f[1] for f in fused} == {A: 1.0, B: 1.0}


def test_keyword_query_drops_stopwords_and_dedupes() -> None:
    assert build_keyword_query("Apa itu prosedur refund? Refund!") == "prosedur | refund"


def test_keyword_query_neutralises_operators() -> None:
    q = build_keyword_query("a&b | !(c:*) 'drop' \"x\" suhu:chiller")
    assert q is not None
    assert not set("&!():*'\"") & set(q.replace(" | ", ""))
    assert "drop" in q and "suhu" in q and "chiller" in q


def test_keyword_query_keeps_unicode_letters() -> None:
    assert build_keyword_query("Café Müller") == "café | müller"


def test_keyword_query_none_when_only_stopwords_or_symbols() -> None:
    assert build_keyword_query("apa yang dan the of") is None
    assert build_keyword_query("?! & | x") is None
