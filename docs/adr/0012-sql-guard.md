# ADR 0012: A layered SQL Guard in front of a read-only executor

- Status: Accepted
- Date: 2026-11-10

## Context

The SQL comes from a language model that reads user questions, database values and example
queries, all of which can carry instructions. It runs against a customer's database. The design
must hold even when the model obeys a hostile question, so the controls cannot live in the prompt.
Nothing the model writes is trusted: it is checked, rewritten and executed only through one path.

## Decision

Seven layers, each in code and each with its own tests:

| # | Layer | Where |
|---|---|---|
| 1 | Parser: one statement, a `SELECT` (CTEs and `UNION` allowed) | `nawa.data.guard` (sqlglot, PostgreSQL dialect) |
| 2 | Allowlist: tables, columns, functions | `nawa.data.guard`, from the semantic layer ([ADR 0011](0011-semantic-layer.md)) |
| 3 | Limit: outer `LIMIT` added or clamped to `DATA_MAX_ROWS` (1000) | `nawa.data.guard` |
| 4 | Database role: the connection test refuses a role that is a superuser, can create objects, or can write to a table; every query also runs in a read-only transaction | `nawa.data.connector`, `nawa.data.executor` |
| 5 | Timeout: `statement_timeout` from `DATA_QUERY_TIMEOUT_S` (10 s), a 2 s `lock_timeout`, and a client timeout 3 s longer | `nawa.data.executor` |
| 6 | Isolation: sources, snapshots, models and logs are tenant tables with forced RLS; the password is stored as Fernet ciphertext and never returned; the platform database is never reachable from this module | migration `0004`, `nawa.core.crypto`, `nawa.data.api` |
| 7 | Audit: every outcome, blocked ones included, is a `query_logs` row with the attempted SQL; creating or deleting a source and activating a model write `audit_logs` | `nawa.data.service`, `nawa.data.api` |

Details that matter:

- **The executed SQL is the rewritten SQL.** The guard qualifies columns against the allowlist
  schema with sqlglot, which expands `*` to allowed columns only, then renders the tree back to
  text. A parser difference between sqlglot and PostgreSQL therefore cannot smuggle in a second
  statement, because only the re-rendered text is run, as a single prepared statement. The
  executor accepts only the `GuardedSql` type, produced by `mark_checked` from a successful verdict.
- **Names are checked in PostgreSQL's way.** Unquoted names fold to lower case, quoted names do
  not (`"Orders"` is not `orders`). A CTE body cannot see itself, so
  `WITH secrets AS (SELECT * FROM secrets)` still hits the real table and is refused.
- **Functions are an allowlist** (aggregates, date, text, math, window, `COALESCE`, `CAST`...).
  Every `pg_*`, `lo_*` and `dblink*` name, `set_config`, `current_setting` and the `*_to_xml` family
  are refused by name, and the final text is scanned again. Schema-qualified calls such as
  `public.sum(x)` are refused because they would call a user-defined function.
- **Whole-row references leak.** `SELECT customers FROM customers` or `c::text` would return the
  omitted `name` column, so any bare table or alias used as a value is refused, as are table alias
  column lists (`customers AS c(a, b, d)`) and a `*` that could not be limited.
- **Two failure kinds drive self-correction.** `forbidden` (anything but a single read-only
  `SELECT`, a table or function that must not be used) is final: no retry, status `blocked`.
  `repairable` (syntax error, unknown column, unknown function, database error, timeout) goes back
  to the model with the previous SQL, at most twice, and every attempt passes the guard again.
  A keyword typo such as `SELEC` is repairable; a real command such as `VACUUM` is not.
- **Reasons never echo the query text.** Messages go to the model and to `query_logs`; they name
  identifiers, not literals.

Alternatives rejected: a deny-list or regular expressions (bypassed by quoting, comments and case);
trusting a read-only role alone (it cannot hide one column of a table it may read); one view or
schema per tenant (assumes control of the customer's database); column-level `GRANT`s only (the
same assumption, and a failure would be silent).

## Consequences

- Residual risks, accepted and documented: an expensive but valid query can run for the full
  timeout (there is no cost estimate before execution); `WITH RECURSIVE` is allowed and bounded
  only by the timeout; casts such as `'x'::regclass` pass and return an object id only; a manager
  can point the API server at any host and port, which is intended for private databases and is
  limited to managers and audited; one connection is opened per query (no pool), trading latency
  for simplicity and for never holding a customer connection open.
- A false positive is possible: a legitimate query using a function that is not on the list is
  refused as repairable, and the model must rephrase. The list grows from the evaluation.
- A hallucinated table name is `forbidden` (final) because it cannot be told apart from a real
  table outside the allowlist; the schema in the prompt keeps this rare.
- Evidence: more than 100 table-driven guard cases (accepted, forbidden, repairable, limits,
  idempotence), executor tests against a writable role proving that writes fail inside the
  read-only transaction, and 10 dangerous questions in the golden set that run through the whole
  pipeline. The measured "dangerous blocked" rate is reported in `docs/evaluation-report-sql.md`
  once `make eval-sql` has run.
