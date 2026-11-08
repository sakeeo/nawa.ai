# ADR 0001: Modular monolith

- Status: Accepted
- Date: 2026-11-06

## Context

NAWA.AI is built and operated by one developer and installed by companies on their own
servers. Every extra deployable unit adds installation steps, failure modes, and operational
cost for the customer.

## Decision

Build one FastAPI application (`nawa`) split into modules (`core`, `workspace`,
`intelligence`, and later `knowledge`, `data`, `agents`, `automation`, `evaluation`). A module
calls another module only through its service functions. import-linter enforces the
dependency rules in CI.

## Consequences

- One image, one migration history, one process to debug; a simple `docker compose` install.
- Module boundaries are explicit, so a module can become a service later if load requires it.
- All modules share one database; table ownership per module is a convention backed by review
  and the import rules, not by separate databases.
