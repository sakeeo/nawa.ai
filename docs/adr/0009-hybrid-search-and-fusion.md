# ADR 0009: Hybrid search with rank fusion, optional reranker

- Status: Accepted
- Date: 2026-11-09

## Context

Questions mix meaning ("how cold must the freezer be") with exact terms (names, figures, codes).
Vector search handles the first well, keyword search the second. The retrieval strategies and the
reranker were compared on the golden set (see the [evaluation report](../evaluation-report.md)).

## Decision

1. **Two candidate lists in one SQL path.** pgvector cosine distance (top `RAG_VECTOR_K` = 30) and
   Postgres full-text with the `simple` configuration over a generated `tsv` column (top
   `RAG_KEYWORD_K` = 30). The keyword query is built from letters and digits only, lower-cased,
   minus a small Indonesian and English stopword list, and joined with `|` (OR). Plain tokens
   cannot inject tsquery operators, and OR keeps recall for natural-language questions.
2. **Reciprocal Rank Fusion** with k = 60 (`RAG_RRF_K`) merges the lists. RRF uses ranks, so the
   incomparable scales (cosine versus `ts_rank`) need no normalisation or tuning, and ties break
   deterministically. Weighted score fusion was rejected: it needs per-corpus weights and score
   normalisation that drift with the data.
3. **Relevance gate on cosine.** Every candidate carries its cosine similarity; the gate refuses
   when the best one is below `RAG_MIN_SIMILARITY` (0.60, calibrated, see below).
4. **Reranker is optional and off by default.** A cross-encoder (`BAAI/bge-reranker-v2-m3` on a
   text-embeddings-inference sidecar, compose profile `reranker`) can reorder the fused top
   `RAG_RERANK_TOP_N` = 20. On any failure the fused order is kept.

## Evidence

| Strategy | Recall@5 | MRR | p50 latency |
|---|---|---|---|
| vector | 1.000 | 0.964 | 162 ms |
| keyword | 0.983 | 0.869 | 5 ms |
| hybrid | 1.000 | 0.946 | 178 ms |

Hybrid did not beat vector-only on this set (MRR 0.018 lower, one or two questions). On 34 short
synthetic documents vector search is near ceiling, so the set cannot show the gain expected on
larger or more keyword-heavy corpora. Hybrid stays the default for that reason, not because of
this measurement.

| Reranker | Recall@5 | MRR | p50 / p95 retrieval latency |
|---|---|---|---|
| off | 0.983 | 0.943 | 116 / 148 ms |
| on | 1.000 | 1.000 | 28.9 s / 42.5 s |

On an 8-thread CPU the cross-encoder takes about 2 s per passage, far above the 3 s time-to-first
-token target, so it is off by default and suited to GPU hosts or a smaller candidate count.
Threshold calibration: a sweep over answerable and unanswerable items picked 0.60, the highest
correct refusal rate (gate refuses 7 of 10 unanswerable) that keeps answerable recall at 0.95
(57 of 60 answered). The previous placeholder 0.35 refused none at the gate.

## Consequences

- The `simple` configuration does no stemming, so Indonesian inflections ("menyimpan",
  "penyimpanan") do not match each other in keyword search. Stemming or a trigram index is a future
  experiment; vector search covers much of the gap.
- 0.60 sits exactly on the recall limit and was calibrated and evaluated on the same 70 items, so
  expect it to need re-calibration for new corpora or another embedding model.
- A reranker timeout silently falls back to the fused order. The evaluation runner marks a rerank
  arm that never reranked as an error, and `RERANKER_TIMEOUT_SECONDS` is configurable.
