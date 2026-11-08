# Architecture

## Components (Phase 0)

```text
Browser --> Next.js (apps/web) --rewrite /api/v1/*--> FastAPI (apps/api, package nawa)
                                                          |
        +--------------------+--------------------+-------+-------------+
        v                    v                    v                     v
 PostgreSQL 16 + pgvector   Redis 7        Ollama (chat, bge-m3)   Langfuse v3
 app data (RLS)             rate limits    local models            LLM traces + cost
 demo data (noesantara)     (jobs later)                           (profile: observability)
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

Boundaries are enforced by import-linter in CI: business modules are independent of each other,
and `core` imports no business module. A module uses another module only through its service
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

## Data model (Phase 0)

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
