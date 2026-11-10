# Evaluation report

## Setup

| Item | Value |
|---|---|
| Date | 2026-11-09 |
| Commit | ffaedb6 |
| Hardware | Linux-7.0.0-43-generic-x86_64-with-glibc2.41, 8 CPU threads, 15 GiB RAM |
| Dataset | 75 items: 60 answerable, 10 unanswerable, 5 injection |
| Documents | synthetic demo set (seed/noesantara_docs) |
| Models (default) | embedding: ollama/bge-m3, generator: deepseek/deepseek-chat, judge: deepseek/deepseek-chat |
| litellm | 1.108.1 |

## Experiment: Chunking strategy

| Arm | Recall@5 | Faithfulness | Status |
|---|---|---|---|
| `chunk-fixed` | 1.000 | 1.000 | ok |
| `chunk-heading` | 0.983 | 0.996 | ok |

Recall@5: `chunk-fixed` is highest at 1.000, ahead of `chunk-heading` by 0.017. Faithfulness: `chunk-fixed` is highest at 1.000, ahead of `chunk-heading` by 0.004.

![Chunking strategy](images/eval-chunking.svg)

## Experiment: Retrieval strategy

| Arm | Recall@5 | MRR | Status |
|---|---|---|---|
| `retrieval-vector` | 1.000 | 0.964 | ok |
| `retrieval-keyword` | 0.983 | 0.869 | ok |
| `retrieval-hybrid` | 1.000 | 0.946 | ok |

Recall@5: tie between `retrieval-vector` and `retrieval-hybrid` (1.000). MRR: `retrieval-vector` is highest at 0.964, ahead of `retrieval-hybrid` by 0.018.

![Retrieval strategy](images/eval-retrieval.svg)

## Experiment: Reranking

Needs the `reranker` compose profile (RERANKER_ENABLED=true, RERANKER_URL).

| Arm | MRR | p50 retrieval latency | p95 retrieval latency | Status |
|---|---|---|---|---|
| `rerank-off` | 0.943 | 116 ms | 148 ms | ok |
| `rerank-on` | 1.000 | 28871 ms | 42483 ms | ok |

MRR: `rerank-on` is highest at 1.000, ahead of `rerank-off` by 0.057. p50 retrieval latency: `rerank-off` is lowest at 116 ms, ahead of `rerank-on` by 28754 ms. p95 retrieval latency: `rerank-off` is lowest at 148 ms, ahead of `rerank-on` by 42335 ms.

![Reranking](images/eval-reranking.svg)

## Experiment: Embedding model

The API arm sends the synthetic demo documents to the provider. mistral-embed returns 1024 dimensions, matching the vector column.

| Arm | Recall@5 | p50 retrieval latency | p95 retrieval latency | Status |
|---|---|---|---|---|
| `embed-bge-m3` | 0.983 | 191 ms | 586 ms | ok |
| `embed-mistral-embed` | n/a | n/a | n/a | skipped: MISTRAL_API_KEY not set |

`embed-mistral-embed` did not produce results (skipped: MISTRAL_API_KEY not set).

## Experiment: Generator model

Local arm runs on the host CPU/GPU; note RAM and CPU used while it runs (not measured by the script).

| Arm | Faithfulness | p50 time to first token | p95 time to first token | Status |
|---|---|---|---|---|
| `gen-qwen2.5-7b` | 0.996 | 82303 ms | 129515 ms | ok |
| `gen-deepseek-chat` | 1.000 | 801 ms | 1218 ms | ok |

Faithfulness: `gen-deepseek-chat` is highest at 1.000, ahead of `gen-qwen2.5-7b` by 0.004. p50 time to first token: `gen-deepseek-chat` is lowest at 801 ms, ahead of `gen-qwen2.5-7b` by 81502 ms. p95 time to first token: `gen-deepseek-chat` is lowest at 1218 ms, ahead of `gen-qwen2.5-7b` by 128298 ms.

![Generator model](images/eval-generator.svg)

## Relevance threshold calibration

Replay of the relevance gate (answer when the best cosine similarity reaches the threshold) over the recorded answerable and unanswerable items.

| Threshold | Refusal precision | Correct refusal rate | Answerable recall |
|---|---|---|---|
| 0.00 | 1.000 | 0.000 | 1.000 |
| 0.05 | 1.000 | 0.000 | 1.000 |
| 0.10 | 1.000 | 0.000 | 1.000 |
| 0.15 | 1.000 | 0.000 | 1.000 |
| 0.20 | 1.000 | 0.000 | 1.000 |
| 0.25 | 1.000 | 0.000 | 1.000 |
| 0.30 | 1.000 | 0.000 | 1.000 |
| 0.35 | 1.000 | 0.000 | 1.000 |
| 0.40 | 1.000 | 0.000 | 1.000 |
| 0.45 | 1.000 | 0.000 | 1.000 |
| 0.50 | 1.000 | 0.100 | 1.000 |
| 0.55 | 1.000 | 0.500 | 1.000 |
| 0.60 (chosen) | 0.700 | 0.700 | 0.950 |
| 0.65 | 0.625 | 1.000 | 0.900 |
| 0.70 | 0.312 | 1.000 | 0.633 |
| 0.75 | 0.185 | 1.000 | 0.267 |
| 0.80 | 0.147 | 1.000 | 0.033 |
| 0.85 | 0.143 | 1.000 | 0.000 |
| 0.90 | 0.143 | 1.000 | 0.000 |

Chosen `RAG_MIN_SIMILARITY` = 0.60: highest correct refusal rate (0.700) with answerable recall at least 0.95 (got 0.950).

## Targets versus results

Configuration `chunk-heading`.

| Metric | Target | Result | Status |
|---|---|---|---|
| Recall@5 | >= 0.850 | 0.983 | met |
| MRR | >= 0.700 | 0.934 | met |
| Faithfulness | >= 0.900 | 0.996 | met |
| Citation accuracy | >= 0.900 | 0.912 | met |
| Correct refusal rate | >= 0.900 | 1.000 | met |
| Injection resistance | >= 1.000 | 1.000 | met |
| p95 time to first token | < 3000 ms | 1049 ms | met |

All targets met.

## Analysis

**Targets.** With the default configuration (heading chunks, hybrid retrieval, no reranker, `deepseek/deepseek-chat` as generator and judge, `RAG_MIN_SIMILARITY` = 0.60) all seven Phase 1 targets are met. Two qualifications apply. First, the generator is the DeepSeek API; the local `qwen2.5:7b` does not meet the latency target (see Generator). Second, faithfulness and citation accuracy are averaged over answered questions only: at threshold 0.60 the gate refused 3 of the 60 answerable questions with heading chunks (57 answered), and 10 of 60 with fixed chunks (50 answered), so those two averages are slightly flattering.

**Chunking.** Fixed 512-token chunks scored Recall@5 1.000 and heading-aware chunks 0.983, a difference of one question out of 60. This does not show that either strategy retrieves better. The threshold interacts with chunking, though: cosine scores of fixed chunks are lower on average, so the calibrated threshold (picked on heading chunks) refused more answerable questions with fixed chunks (10 versus 3). The threshold would need its own calibration for another chunker.

**Retrieval.** Vector and hybrid both reach Recall@5 1.000; keyword alone is lower (0.983) with clearly weaker ranking (MRR 0.869 versus 0.964 vector and 0.946 hybrid). Hybrid did not beat vector-only on this set: its MRR is 0.018 lower, which is one or two questions. On 34 short synthetic documents, vector search is already near ceiling, so the set cannot show the benefit hybrid is expected to bring on larger or more keyword-heavy corpora. Keyword search is far cheaper (p50 5 ms versus 160 to 180 ms, which is mostly the query embedding).

**Reranking.** The cross-encoder (`bge-reranker-v2-m3`) lifted MRR from 0.943 to 1.000 and Recall@5 from 0.983 to 1.000, but on this 8-thread CPU it adds about 29 s at p50 and 42 s at p95 per query (about 2 s per passage, 20 candidates). That is more than 10 times the 3 s TTFT target, so it stays off by default. It is only usable with a GPU or a smaller candidate count. A first attempt looked fine only because every call hit the 10 s timeout and silently fell back to the fused order; the runner now marks such an arm as an error, and the timeout is configurable (`RERANKER_TIMEOUT_SECONDS`).

**Embedding.** Only the local `bge-m3` ran (Recall@5 0.983, p50 191 ms, p95 586 ms). The API arm was skipped because no `MISTRAL_API_KEY` was set, so there is no local-versus-API comparison.

**Generator.** `deepseek-chat` scored faithfulness 1.000, citation accuracy 0.883 and injection resistance 1.000 with TTFT p50 0.8 s and p95 1.2 s. The local `qwen2.5:7b` scored faithfulness 0.996, citation accuracy 0.831 and injection resistance 0.800 (one of five injections followed), with TTFT p50 82 s and p95 130 s on CPU; one item failed and was excluded. Retrieval was identical for both (Recall@5 0.983), so the gap comes from the generator. A 7B model on CPU is therefore not interactive on this hardware; it fits batch use or a GPU host. RAM and CPU use of the local arm were not measured. Both generator arms ran at the earlier threshold 0.35 and commit `ee1c15c`, not at 0.60, and were not rerun (about 90 minutes); the retrieval, reranking and embedding metrics do not depend on the threshold.

**Threshold.** At the placeholder 0.35 the gate refused none of the 10 unanswerable questions: the 1.000 correct refusal rate came from the model answering "not found". The sweep picks 0.60 (gate refuses 7 of 10 unanswerable, answers 57 of 60 answerable), the highest correct refusal rate that keeps answerable recall at 0.95. This sits exactly on the recall limit; 0.55 keeps recall at 1.000 but refuses only 5 of 10. With 10 unanswerable items the choice is sensitive to one or two questions, and it was calibrated and evaluated on the same set, so the end-to-end numbers above are optimistic for unseen questions.

**Judge.** Faithfulness of 0.996 to 1.000 in every arm suggests a lenient judge or an easy synthetic set. No arm shows a difference the judge could resolve. Treat faithfulness as a floor check, not a ranking signal.

## Limitations

- The judge is one LLM (DeepSeek) that also sees synthetic Indonesian text; its verdicts are not human-verified, and judge errors are excluded from the averages.
- The golden set has 75 items (60 answerable, 10 unanswerable, 5 injection); one item moves a rate by 1.7, 10 and 20 points respectively, so small gaps between arms are within noise.
- All documents are synthetic and generated by one process; real company documents are messier.
- Generation uses provider-default sampling and no seed, so reruns differ slightly; latency depends on the host and on API load at the time.
