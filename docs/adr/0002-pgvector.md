# ADR 0002: pgvector instead of a separate vector database

- Status: Accepted
- Date: 2026-11-06

## Context

Retrieval (Phase 1) needs vector search, keyword search, and strict workspace isolation.
Self-hosted installs should run as few services as possible.

## Decision

Store embeddings in PostgreSQL 16 with pgvector (HNSW indexes) next to the relational data and
the full-text index. The compose stack already uses the `pgvector/pgvector` image.

## Consequences

- Hybrid search (vector plus full-text) is one SQL query, and row-level security protects
  vectors exactly like other tenant data.
- One backup covers everything.
- Very large corpora (tens of millions of chunks) may need a dedicated engine later; that is
  outside the target scale of a single-organization install.
