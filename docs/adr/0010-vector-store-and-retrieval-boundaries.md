# ADR 0010: Vectors in PostgreSQL, narrow module-boundary exceptions

- Status: Accepted
- Date: 2026-11-09
- Extends [ADR 0002](0002-pgvector.md)

## Context

ADR 0002 chose pgvector over a separate vector database. Phase 1 implements it and adds
cross-module calls that the import-linter independence contract would otherwise forbid.

## Decision

**Vector store.** `chunks.embedding` is `vector(1024)` (BGE-M3) with an HNSW index using cosine
operators, next to a generated `tsv` column with a GIN index. The `chunks` table carries
`workspace_id` with row-level security like every tenant table, so a retrieval query that forgets
a filter still cannot read another workspace, and vectors need no separate access control. One
Postgres means one backup and no second service to run offline. A dedicated vector database
was rejected for the target scale of one organization.

**Revisit when** a workspace holds on the order of millions of chunks, HNSW build or insert time
hurts ingestion, or filtered search latency exceeds the interactive budget. Changing the embedding
model also changes the column dimension and requires re-embedding everything.

**Import exceptions.** All are listed in `pyproject.toml` under the independence contract and are
single edges, not blanket permissions:

| Exception | Why |
|---|---|
| `nawa.knowledge.api -> nawa.workspace.deps` | Role checks (`ViewerCtx`, `MemberCtx`, `ManagerCtx`) live in one place; copying them would fork RBAC. |
| `nawa.knowledge.api -> nawa.workspace.repository` | Chat reads instance settings (setup state, chosen model) read-only. |
| `nawa.evaluation.runner -> nawa.knowledge.answer` | The evaluation must run the real answering pipeline, not a copy. |
| `nawa.evaluation.runner -> nawa.knowledge.corpus` | It ingests the demo documents through the real ingestion code. |
| `nawa.evaluation.runner -> nawa.knowledge.rerank` | It builds the same reranker the chat uses. |

The evaluation CLI also loads other modules' ORM models by name with `importlib`, so foreign keys
resolve without a static import.

## Consequences

- Retrieval, ingestion and evaluation share one database and one transaction model.
- The evaluation depends on three knowledge entry points; renaming them breaks the runner, and
  the import-linter keeps the dependency list explicit and short.
- Vector search at very large scale is out of scope for this architecture.
