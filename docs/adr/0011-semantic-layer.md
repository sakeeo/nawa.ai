# ADR 0011: A YAML semantic layer is the allowlist for Text-to-SQL

- Status: Accepted
- Date: 2026-11-10

## Context

The data analyst turns a business question into SQL over a customer's own PostgreSQL database.
A model that sees only raw table and column names guesses what "revenue" or "outlet" means, and a
model that may touch any table can read data it should never see (personal data, payroll).
The platform needs one place that says what the model may use and what the business terms mean.

## Decision

1. **A YAML document per data source, stored in the platform database** (`semantic_models`:
   versioned, at most one active version per source through a partial unique index). Managers edit
   it in the web UI. Alternatives rejected: files in the repository (not editable per tenant, no
   history per workspace) and a model-generated description (not reviewable, not stable).
2. **It is the allowlist by construction.** `tables` lists every table and column the model may
   use. A column that is not listed does not exist for the pipeline; a column marked `sensitive`
   is listed but excluded. The same allowlist feeds the prompt, the SQL Guard
   ([ADR 0012](0012-sql-guard.md)) and the sampling of example values during discovery, so the
   three cannot disagree. The demo model omits `customers.name`.
3. **Validated against the discovered schema before it is saved.** Unknown tables or columns,
   joins over unlisted tables, metric or dimension SQL that does not parse or reaches a column
   outside the allowlist, a metric that refers to itself, duplicate YAML keys and a `time_anchor`
   that is not a single `SELECT` are all reported as a list of problems (HTTP 422).
4. **Metrics and dimensions are text expressions, not a compiler.** `revenue:
   SUM(order_items.quantity * order_items.unit_price)` is a definition the model copies into
   its SQL. A metric may name another metric; the prompt shows it written out
   (`expand_metric`) so the model copies one expression. A compiled metrics engine was rejected
   as too large for the benefit: the model still writes the joins, and the guard checks the result.
5. **`time_anchor` is "today".** One `SELECT` (demo: `MAX(created_at)::date FROM orders`) is run at
   ask time and given to the model, so "bulan ini" means the month of the newest data and not the
   wall clock. Without it, the demo data (calendar 2025) would answer every "this month" question
   with an empty result.
6. **Drafts are deterministic.** "Create draft from schema" lists every table and column and the
   joins implied by foreign keys; it calls no model.
7. **Sample values obey the allowlist.** Discovery stores enum-like text values (at most 20
   distinct, each at most 40 characters) only for allowlisted columns; with no model yet, it
   stores none. Values reach the model, so they follow the same provider policy as everything
   else, and they enter the prompt inside an untrusted block.

## Consequences

- The model can still choose a wrong join or aggregation inside the allowlist; the semantic
  layer narrows the space but does not prove correctness. The golden dataset measures it
  (`docs/evaluation-report-sql.md`).
- Quality depends on the author of the YAML: synonyms in the users' language are what let
  lexical schema linking find a table ([ADR 0013](0013-schema-linking.md)).
- The snapshot goes stale when the customer's schema changes; a manager must run Discover again,
  and saving the model again after that picks up new sample values.
- Old versions are kept, but there is no UI to roll back to one.
- Each ask costs one extra query for the anchor.
