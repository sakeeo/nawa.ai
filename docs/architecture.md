# Architecture

## Components

```text
Browser --> Next.js (apps/web) --rewrite /api/v1/*--> FastAPI (apps/api, package nawa)
                                                          |
        +--------------------+--------------------+-------+-------------+
        v                    v                    v                     v
 PostgreSQL 16 + pgvector   Redis 7        Ollama (chat, bge-m3)   Langfuse v3
 app data (RLS), chunks     rate limits,   local models            LLM traces + cost
 and vectors, demo data     ARQ job queue                          (profile: observability)

 worker (ARQ, same image as the API)   runs ingestion; shares the `uploads` volume with the API
 reranker (optional, profile)          text-embeddings-inference with bge-reranker-v2-m3
```

The web app and the API share one origin through a Next.js rewrite, so the session cookies
need no CORS configuration. The access and refresh tokens are `HttpOnly`; a readable CSRF
cookie is echoed in the `X-CSRF-Token` header on every state-changing request.

## Modules

| Module | Owns | Talks to |
|---|---|---|
| `nawa.core` | settings, database engine and RLS context, errors, security helpers, audit log, rate limiting | nothing else in `nawa` |
| `nawa.workspace` | users, workspaces, memberships, invites, refresh tokens, instance settings, first-run setup | `core` |
| `nawa.intelligence` | LLM gateway, offline policy, prompt registry, tracing | `core`, and `workspace` only for the admin LLM test route |
| `nawa.knowledge` | documents, ingestion worker, hybrid retrieval, reranker, relevance gate, citations, chat, feedback | `core`, `intelligence`; `workspace` only for role checks and instance settings (two documented import exceptions) |
| `nawa.data` | data sources and encrypted credentials, schema discovery, YAML semantic layer, schema linking, SQL Guard, read-only executor, Text-to-SQL, charts, insight, approved queries, query log | `core`, `intelligence`; `workspace` only for role checks and instance settings (same two exceptions as `knowledge`) |
| `nawa.evaluation` | golden datasets, metrics, LLM judge, experiments, reports for retrieval and Text-to-SQL | `core`, `intelligence`; three `knowledge` entry points (answer, corpus, rerank) and the public `data` entry points used by the SQL evaluation, by exception |

Boundaries are enforced by import-linter in CI: business modules are independent of each other,
and `core` imports no business module. The narrow exceptions are listed in `pyproject.toml`; the
Phase 1 ones are justified in [ADR 0010](adr/0010-vector-store-and-retrieval-boundaries.md), and the
Phase 2 ones (the data API reading roles and the AI provider, the SQL evaluation driving the real
pipeline and checking its references with the guard) follow the same reasoning. A module uses another module only through its service
functions, never its tables.

## Workspace isolation

Every tenant-scoped table carries `workspace_id` and has Postgres row-level security enabled.
Each request sets transaction-local settings that the policies read:

| Setting | Meaning |
|---|---|
| `app.user_id` | authenticated user |
| `app.workspace_id` | workspace the request is scoped to, set after a membership check |
| `app.is_admin` | instance administrators, and system flows such as invite acceptance |

The API connects as a role that is neither the table owner nor `BYPASSRLS`, so a query that
forgets a `WHERE workspace_id = ...` still cannot read another workspace. Migrations run as the
owner role.

## Roles

An instance administrator (`users.is_admin`) can act as admin in every workspace. Inside a
workspace, a membership has the role `manager`, `member`, or `viewer`. Self-signup does not
exist: the first administrator is created by the setup wizard, and everyone else joins through
a single-use invitation created by an administrator.

## LLM gateway

All model calls go through `LLMGateway` in `nawa.intelligence.gateway`:

1. Candidate models: the model for the provider chosen in the setup wizard (`LLM_MODEL` for an
   external provider, `ollama/<OLLAMA_CHAT_MODEL>` for the local one), then `LLM_FALLBACK_MODEL`.
2. With `OFFLINE_MODE=true`, external models are removed. If none remain, the call fails with
   `403 Offline Mode` before any network access.
3. LiteLLM sends the request. When Langfuse keys are set, Langfuse receives the trace: prompt
   name and version, user, tokens, latency, and cost.
4. Embeddings always use the local `ollama/bge-m3` model.

Prompts live in `apps/api/nawa/intelligence/prompts/<name>.v<version>.yaml`. The admin route
`POST /api/v1/llm/chat` runs one message through the gateway for connectivity checks.

## Knowledge API (Phase 1)

All routes live under `/api/v1/workspaces/{workspace_id}`; unsafe methods need the CSRF header.

| Method | Path | Minimum role |
|---|---|---|
| POST | `/documents` (multipart) | manager |
| GET | `/documents`, `/documents/{id}` | viewer |
| POST | `/documents/{id}/retry` | manager |
| DELETE | `/documents/{id}` | manager |
| GET | `/chunks/{chunk_id}` | viewer |
| POST | `/chat` (Server-Sent Events) | member |
| GET | `/conversations`, `/conversations/{id}` | member (own only) |
| POST | `/messages/{id}/feedback` | member (own conversations) |

`/chat` streams `data: <json>` events with a `type` field: `meta`, `token`, `citations`
(or `refusal` instead of tokens when the documents do not answer), `done`, and `error`. The
assistant message is stored just before `done`; a client that disconnects leaves only its own
question behind. Chat is limited to `CHAT_LIMIT_PER_MINUTE` questions per user (default 20).

## Data API (Phase 2)

All routes live under `/api/v1/workspaces/{workspace_id}`; unsafe methods need the CSRF header.

| Method | Path | Minimum role |
|---|---|---|
| POST | `/data-sources` (encrypts the password, tests the connection) | manager |
| GET | `/data-sources` | viewer |
| POST | `/data-sources/{id}/test`, `/data-sources/{id}/discover` | manager |
| DELETE | `/data-sources/{id}` | manager |
| GET | `/data-sources/{id}/semantic-model` | viewer |
| POST | `/data-sources/{id}/semantic-model/draft` | manager |
| PUT | `/data-sources/{id}/semantic-model` (validates, 422 with `problems`) | manager |
| POST | `/data/ask` | member |
| POST | `/data/queries/{id}/insight` | member (own query) or manager |
| GET | `/data/queries` | member (own) or manager (all) |
| POST | `/data/queries/{id}/feedback` | member (own query) |

`POST /data/ask` returns JSON, not a stream: the question, status (`ok`, `blocked`, `error` or
`clarification`), the SQL that ran, columns and rows, a chart spec, computed anomaly notes and the
query id. The narrative is a second call, `.../insight`, so the latency target applies to the
answer itself. Asking is limited to `DATA_ASK_LIMIT_PER_MINUTE` per user (default 20).

**Question to result.** `ask` requires a source that passed its connection test, a schema snapshot
and an active semantic model, then:

1. Clean the question (control characters, 1000 characters) and read `time_anchor` for "today".
2. Link the schema ([ADR 0013](adr/0013-schema-linking.md)) and look up approved examples of the
   same source (cosine at least 0.75, at most 3).
3. Ask the model for JSON `{sql, assumptions, clarification}`; the question, sample values and
   examples enter the prompt only inside untrusted blocks.
4. Check the SQL with the guard ([ADR 0012](adr/0012-sql-guard.md)): a `forbidden` verdict ends
   the request as `blocked`; a `repairable` one or a database error goes back to the model with the
   error, at most twice.
5. Run the rewritten SQL in a read-only transaction with a timeout and a row cap.
6. Write a `query_logs` row for the outcome, then choose the chart from the result shape (KPI, bar,
   line or table) and compute anomaly notes for a time series (z-score, at least 6 points).

**Insight.** The stored, guarded SQL is checked again against the current model and run again; the
model phrases the result, every number in its text must appear in the rows or in statistics
computed here, and a text with an unknown number is replaced by a fixed sentence built from those
statistics. The result is cached on the query log.

**Approved queries.** A thumbs-up on a successful answer stores the question, its SQL and an
embedding (`approved_queries`); a thumbs-down removes it.

## Knowledge flows

**Upload to ready.** A manager uploads a file (PDF, DOCX, TXT or MD, at most `MAX_UPLOAD_BYTES`
and `MAX_PDF_PAGES`). The API stores it under `UPLOAD_DIR`, records a `documents` row with status
`queued` (a duplicate SHA-256 in the same knowledge base returns 409) and enqueues an ARQ job. The
worker sets `processing`, extracts blocks, normalizes text, chunks it
([ADR 0008](adr/0008-chunking-strategy.md)), embeds the chunks through the gateway
(`ollama/bge-m3`) and writes them in one transaction, then sets `ready`. Any failure leaves the
document `failed` with a short message and no partial chunks; `/retry` re-queues it.

**Question to answer.** `POST /chat` runs, in order:

1. Sanitize the question and rate-limit per user.
2. Retrieve: vector and keyword candidates fused with RRF ([ADR 0009](adr/0009-hybrid-search-and-fusion.md)).
3. Relevance gate: refuse when the best cosine similarity is below `RAG_MIN_SIMILARITY`.
4. Optional rerank, then assemble up to `RAG_CONTEXT_K` passages within `RAG_CONTEXT_MAX_TOKENS`,
   scanning each passage for injection patterns. Passages are data, never instructions.
5. Stream the answer from the `answer` prompt; markers like `[1]` are mapped to citations, and
   markers that match no passage are reported as invalid.
6. Persist the assistant message and its citations, then send `done`.

When the gate refuses, the `refuse` prompt's fixed text is sent as a `refusal` event and no model
call produces an answer.

**SSE events** (`data: <json>` with a `type` field):

| Type | Payload |
|---|---|
| `meta` | retrieved count, whether reranked, best similarity, gate reason |
| `token` | `text` fragment of the answer |
| `refusal` | `text`, instead of tokens when the documents do not answer |
| `citations` | clickable citations: marker, document, page, section, chunk id; invalid markers |
| `done` | model, prompt name and version, token counts, time to first token, total time, whether refused |
| `error` | `code` and `message`; the assistant message is not stored |

**Permissions.** Viewer: read documents and chunks. Member: ask questions, read own
conversations, give feedback. Manager: upload, retry and delete documents. Administrators act as
manager in every workspace.

## Data model

```text
users (global) ----< memberships >---- workspaces
                       role: manager | member | viewer

users ----< refresh_tokens (rotated, chain revoked on reuse)
workspaces ----< invites (token stored as hash, expiry, single use)
instance_settings (single row: setup state, AI provider, setup token hash)
audit_logs

workspaces ----< knowledge_bases ----< documents ----< chunks
              documents.status: queued | processing | ready | failed (unique sha256 per base)
              chunks: text, page, section_path, heading, token_count,
                      embedding vector(1024) [HNSW cosine], tsv tsvector [GIN, 'simple']
workspaces ----< conversations ----< messages ----< citations (marker -> chunk)
                 (owner: user)         messages ----< feedback (value, comment)
workspaces ----< eval_runs ----< eval_results (question_id, retrieved, answer, metrics)

workspaces ----< data_sources (password encrypted, status: untested | ok | failed)
                   data_sources ----< schema_snapshots (tables, columns, keys, sample values; jsonb)
                   data_sources ----< semantic_models (YAML, version, one active)
                   data_sources ----< approved_queries (question, sql, embedding vector(1024) [HNSW])
workspaces ----< query_logs (question, sql, status: ok | blocked | error | clarification,
                             blocked_reason, attempts, row_count, duration_ms, insight, feedback;
                             data_source_id set to NULL when the source is deleted)
```

Every table above carries `workspace_id` (`eval_results` inherits it through `eval_runs`) and
has row-level security forced. The customer's own database (a data source) is separate and is
reached only through the read-only executor.

## Demo data

The `noesantara` database holds the fictional restaurant chain Resto Noesantara: 5 outlets,
72 menu items, 16 ingredients with recipes, 500 loyalty members, one year of dine-in, takeaway,
and delivery orders, monthly ingredient stock, and expenses. In August, the beef supplier fails
to deliver to Bandung, so all beef dishes are unavailable and its sales drop by about 30%.
The generator is deterministic; see `seed/README.md`. `make seed` also creates a SELECT-only role in
that database; the data analyst connects with it, using `seed/noesantara_semantic.yaml` as its
semantic layer (`customers.name` is deliberately left out).
