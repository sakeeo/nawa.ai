# NAWA.AI

**Self-hosted enterprise intelligence and automation platform.**
*From business knowledge to intelligent execution.*

NAWA.AI answers questions from company documents, analyses business data in natural language,
and runs AI agents with human approval, all on the company's own infrastructure. Data never
leaves the host, and the platform can run fully offline with local models.

> Status: **Phase 0, Foundation.** First-run setup wizard, authentication, workspaces with
> row-level security, an offline-aware LLM gateway with Langfuse tracing, and demo data.

## Why self-hosted

Many companies cannot send documents or business data to third-party AI services. NAWA.AI is an
installed product, not a SaaS: one installation serves one organization, local models are the
default, and external providers are opt-in and blocked entirely in offline mode.

## Architecture

```text
Web (Next.js) --/api/v1--> API (FastAPI, modular monolith)
                             |- core          config, database and RLS context, errors, audit
                             |- workspace     users, workspaces, members, invites, setup
                             '- intelligence  LLM gateway (LiteLLM), offline policy, prompts, tracing
                                    |
              PostgreSQL 16 + pgvector, Redis, Ollama (local LLM + BGE-M3), Langfuse
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
`make dev-lite` starts it without Langfuse. Open http://localhost:3000.

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

## Development

| Command | Purpose |
|---|---|
| `make dev` | Start the full stack |
| `make test` | API and web tests |
| `make lint` | ruff, mypy, import-linter, eslint, tsc |
| `make offline-smoke` | Offline acceptance check |

Python uses `uv`; the frontend uses `pnpm`. Tests never call a real LLM; they use a fake client.

API integration tests need a PostgreSQL superuser URL in `TEST_DATABASE_OWNER_URL`; without it
they are skipped. The demo data loader lives in [seed/](seed/README.md).

## Technical decisions

- [ADR 0001: Modular monolith](docs/adr/0001-modular-monolith.md)
- [ADR 0002: pgvector instead of a separate vector database](docs/adr/0002-pgvector.md)
- [ADR 0007: Self-hosted and local-first](docs/adr/0007-self-hosted-local-first.md)

## Roadmap

| Phase | Scope |
|---|---|
| 0 | Foundation (current) |
| 1 | Knowledge intelligence: RAG with citations and evaluation |
| 2 | Business intelligence: safe text-to-SQL with charts |
| 3 | Multi-agent analysis with human-in-the-loop |
| 4 | Scheduled workflows with approvals and audit |
| 5 | Polish and launch |
