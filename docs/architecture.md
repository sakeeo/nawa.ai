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
| `nawa.evaluation` | golden dataset, metrics, LLM judge, experiments, report | `core`, `intelligence`; three `knowledge` entry points (answer, corpus, rerank) by exception |

Boundaries are enforced by import-linter in CI: business modules are independent of each other,
and `core` imports no business module. The five narrow exceptions are listed and justified in
[ADR 0010](adr/0010-vector-store-and-retrieval-boundaries.md). A module uses another module only through its service
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
```

Every table above carries `workspace_id` (`eval_results` inherits it through `eval_runs`) and
has row-level security forced.

```text
users (global) ----< memberships >---- workspaces
                       role: manager | member | viewer

users ----< refresh_tokens (rotated, chain revoked on reuse)
workspaces ----< invites (token stored as hash, expiry, single use)
instance_settings (single row: setup state, AI provider, setup token hash)
audit_logs
```

## Demo data

The `noesantara` database holds the fictional restaurant chain Resto Noesantara: 5 outlets,
72 menu items, 16 ingredients with recipes, 500 loyalty members, one year of dine-in, takeaway,
and delivery orders, monthly ingredient stock, and expenses. In August, the beef supplier fails
to deliver to Bandung, so all beef dishes are unavailable and its sales drop by about 30%.
The generator is deterministic; see `seed/README.md`.
