# Evaluation report

## Setup

| Item | Value |
|---|---|
| Commit | abc1234 |
| Dataset | 4 items |

## Experiment: Chunking strategy

| Arm | Recall@5 | Faithfulness | Status |
|---|---|---|---|
| `chunk-fixed` | 0.800 | 0.900 | ok |
| `chunk-heading` | 0.900 | 0.900 | ok |

Recall@5: `chunk-heading` is highest at 0.900, ahead of `chunk-fixed` by 0.100. Faithfulness: tie between `chunk-fixed` and `chunk-heading` (0.900).

![Chunking strategy](images/eval-chunking.svg)

## Experiment: Embedding model

API arm sends synthetic documents only.

| Arm | Recall@5 | p50 retrieval latency | Status |
|---|---|---|---|
| `embed-local` | 0.875 | 120 ms | ok |
| `embed-api` | n/a | n/a | skipped: MISTRAL_API_KEY not set |

`embed-api` did not produce results (skipped: MISTRAL_API_KEY not set).

## Relevance threshold calibration

Replay of the relevance gate (answer when the best cosine similarity reaches the threshold) over the recorded answerable and unanswerable items.

| Threshold | Refusal precision | Correct refusal rate | Answerable recall |
|---|---|---|---|
| 0.00 | 1.000 | 0.000 | 1.000 |
| 0.20 | 1.000 | 0.000 | 1.000 |
| 0.40 (chosen) | 1.000 | 0.500 | 1.000 |
| 0.60 | 0.667 | 1.000 | 0.500 |

Chosen `RAG_MIN_SIMILARITY` = 0.40: highest correct refusal rate (0.500) with answerable recall at least 1.00 (got 1.000).

## Targets versus results

Configuration `chunk-heading`.

| Metric | Target | Result | Status |
|---|---|---|---|
| Recall@5 | >= 0.850 | 0.900 | met |
| MRR | >= 0.700 | 0.650 | missed (-0.050) |
| Faithfulness | >= 0.900 | 0.950 | met |
| Citation accuracy | >= 0.900 | 0.900 | met |
| Correct refusal rate | >= 0.900 | 1.000 | met |
| Injection resistance | >= 1.000 | 1.000 | met |
| p95 time to first token | < 3000 ms | 3500 ms | missed (+500 ms) |

Missed targets: MRR, p95 time to first token. Likely causes are in the analysis below.

## Analysis

_Not written yet: add the analysis from the real numbers._

## Limitations

- Small dataset.
