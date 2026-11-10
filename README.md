# NAWA.AI

**Self-hosted enterprise intelligence and automation platform.**
*From business knowledge to intelligent execution.*

NAWA.AI answers questions from company documents, analyses business data in natural language,
and runs AI agents with human approval, all on the company's own infrastructure. Data never
leaves the host, and the platform can run fully offline with local models.

> Status: **Phase 1, Knowledge Intelligence.** Document upload and background ingestion, hybrid
> retrieval with citations, an AI Assistant that refuses when the documents do not answer, and an
> evaluation engine with a published [report](docs/evaluation-report.md). Phase 0 (setup wizard,
> authentication, workspaces with row-level security, offline-aware LLM gateway, demo data) is included.

## Why self-hosted

Many companies cannot send documents or business data to third-party AI services. NAWA.AI is an
installed product, not a SaaS: one installation serves one organization, local models are the
default, and external providers are opt-in and blocked entirely in offline mode.

## Architecture

```text
Web (Next.js) --/api/v1--> API (FastAPI, modular monolith)
                             |- core          config, database and RLS context, errors, audit
                             |- workspace     users, workspaces, members, invites, setup
                             |- intelligence  LLM gateway (LiteLLM), offline policy, prompts, tracing
                             |- knowledge     documents, ingestion, hybrid retrieval, chat, citations
                             '- evaluation    golden dataset, metrics, experiments, report
                                    |
              PostgreSQL 16 + pgvector, Redis (+ ARQ worker), Ollama (local LLM + BGE-M3),
              optional reranker, Langfuse
```

See [docs/architecture.md](docs/architecture.md) and the [ADRs](docs/adr/).

## Quick install

Requirements: Docker with Compose v2 and GNU Make.

```bash
git clone <repository-url> nawa.ai && cd nawa.ai
cp .env.example .env      # then set every secret; see the comments in the file
make dev
```

`make dev` builds and starts the stack, including Langfuse (profile `observability`).
`make dev-lite` starts it without Langfuse (leave the `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY` and `LANGFUSE_INIT_*` values in `.env` empty then). With `make dev`,
Langfuse creates its project and first user from those values on first start, and every LLM call
is traced; sign in at http://localhost:3100 with `LANGFUSE_INIT_USER_EMAIL` and
`LANGFUSE_INIT_USER_PASSWORD`. Open http://localhost:3000.

On first start the API logs a one-time setup token:

```bash
docker compose logs api | grep -i "setup token"
```

Paste it into the setup wizard together with the first administrator's email and password.
The token stops working once setup is complete.

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API | http://localhost:8000 |
| Langfuse (traces, cost) | http://localhost:3100 |

Compose profile `local-llm` pulls the local chat model and the BGE-M3 embedding model into
Ollama. Embeddings are always local.

Compose profile `reranker` starts a cross-encoder reranker (text-embeddings-inference with
`BAAI/bge-reranker-v2-m3`, about 2.3 GB of weights cached in a volume). Start it with
`docker compose --profile reranker up -d reranker` and set `RERANKER_ENABLED=true` in `.env`.
Without it, retrieval uses the fused ranking only; if the reranker is down at query time the
same fallback applies and a warning is logged.

### Offline mode

Set `OFFLINE_MODE=true` in `.env`. Every external provider is blocked and the local model is
used. `make offline-smoke` runs the stack on a Docker network with no internet route and checks
that the local model answers while outbound access fails. The first run downloads several GB of
model weights.

### Hardware

| Profile | Spec |
|---|---|
| Minimum (no GPU) | 4 vCPU, 16 GB RAM, 50 GB disk |
| Recommended | 8 vCPU, 32 GB RAM, GPU with 16-24 GB VRAM |

## How the assistant answers

Upload documents on the Knowledge page (managers) and ask questions on the AI Assistant page (members).
Each question is embedded locally, matched against document chunks by vector and keyword search, and merged
with Reciprocal Rank Fusion. If the best match is not similar enough (`RAG_MIN_SIMILARITY`, 0.60), the
assistant says the documents do not answer instead of guessing. Otherwise the top passages go to the model,
which must cite them as `[1]`, `[2]`; each citation links to the exact passage. Document text is treated as
data: instructions inside a document are never followed. Ingestion, retrieval and the local chat model all
run without internet, so `OFFLINE_MODE=true` keeps working; only the evaluation judge and the optional API
experiment arms use an external provider.

Measured quality, targets and limitations: [docs/evaluation-report.md](docs/evaluation-report.md).

## Development

| Command | Purpose |
|---|---|
| `make dev` | Start the full stack |
| `make seed` | Create the `noesantara` demo database and load the demo data |
| `make test` | API and web tests |
| `make lint` | ruff, mypy, import-linter, eslint, tsc |
| `make eval` | Run the golden dataset (`evals/golden.yaml`) and print the quality metrics |
| `make eval-experiments NAME=<x>` | Run one experiment (`chunking`, `retrieval`, `reranking`, `embedding`, `generator`, or `all`) and save JSON to `evals/results/` |
| `make eval-report` | Render `docs/evaluation-report.md` and `docs/images/eval-*.svg` from the saved results |
| `make offline-smoke` | Offline acceptance check |

`make eval` ingests the demo documents into a persistent `nawa-eval` workspace and scores 75
golden questions (60 answerable, 10 unanswerable, 5 prompt-injection traps) on Recall@5, MRR,
faithfulness, citation accuracy, refusal rate, injection resistance and P95 time-to-first-token.
It needs the running stack (database, Ollama embeddings) and `DEEPSEEK_API_KEY` for the judge, uses
synthetic data only, and refuses to run when `OFFLINE_MODE=true`. Use `make eval LIMIT=5` for a quick
check. Results are stored in `eval_runs` / `eval_results`.

The experiments are defined in `evals/experiments.yaml`; each arm records its configuration, commit and
models. They take hours on CPU (a local 7B generator needs about 1.6 minutes per question), so run one
at a time. The `reranking` experiment needs `docker compose --profile reranker up -d reranker`,
`RERANKER_ENABLED=true`, and a long `RERANKER_TIMEOUT_SECONDS` (the make target sets 180). The embedding
API arm is skipped unless `MISTRAL_API_KEY` is set. Only synthetic data is sent to external providers.

The `worker` service (ARQ on Redis) runs background ingestion and shares the `uploads` volume with the API.
The optional `reranker` service (compose profile `reranker`, about 2.3 GB of weights, cached in a volume)
runs a cross-encoder; on CPU it takes about 2 s per passage, so it is off by default.

Text-to-SQL evaluation (Phase 2): `make eval-sql` runs the baseline arm of `evals/sql_experiments.yaml`
(50 answerable and 10 dangerous questions from `evals/sql_golden.yaml`) through the production pipeline against
the demo database; run `make seed` first with `DEMO_DB_READONLY_PASSWORD` set. `make eval-sql-experiments`
runs every arm (baseline, no schema linking, no self-correction, local model; `NAME=<arm>` for one) and
`make eval-sql-report` writes `docs/evaluation-report-sql.md` from `evals/results/sql-*.json`, keeping the
hand-written analysis. Like `make eval` it needs Ollama for embeddings and `DEEPSEEK_API_KEY` for the default
generator, uses synthetic data only, and refuses to run when `OFFLINE_MODE=true`. `LIMIT=5` gives a quick dry run.

Data analyst settings (Phase 2): `DATA_ENCRYPTION_KEY` (Fernet key that encrypts data source passwords; without it
creating a data source returns 503), `DEMO_DB_READONLY_USER` / `DEMO_DB_READONLY_PASSWORD` (a SELECT-only role that
`make seed` creates in the demo database; skipped when the password is empty), and the tuning values
`DATA_QUERY_TIMEOUT_S`, `DATA_MAX_ROWS`, `DATA_LINK_TOP_TABLES`, `DATA_ASK_LIMIT_PER_MINUTE`.

Python uses `uv`; the frontend uses `pnpm`. Tests never call a real LLM; they use a fake client.

API integration tests need a PostgreSQL superuser URL in `TEST_DATABASE_OWNER_URL`; without it
they are skipped. The demo data loader lives in [seed/](seed/README.md).

## Technical decisions

- [ADR 0001: Modular monolith](docs/adr/0001-modular-monolith.md)
- [ADR 0002: pgvector instead of a separate vector database](docs/adr/0002-pgvector.md)
- [ADR 0007: Self-hosted and local-first](docs/adr/0007-self-hosted-local-first.md)
- [ADR 0008: Heading-aware chunking](docs/adr/0008-chunking-strategy.md)
- [ADR 0009: Hybrid search with rank fusion, optional reranker](docs/adr/0009-hybrid-search-and-fusion.md)
- [ADR 0010: Vectors in PostgreSQL, narrow module-boundary exceptions](docs/adr/0010-vector-store-and-retrieval-boundaries.md)

## Roadmap

| Phase | Scope |
|---|---|
| 0 | Foundation |
| 1 | Knowledge intelligence: RAG with citations and evaluation (current) |
| 2 | Business intelligence: safe text-to-SQL with charts |
| 3 | Multi-agent analysis with human-in-the-loop |
| 4 | Scheduled workflows with approvals and audit |
| 5 | Polish and launch |
