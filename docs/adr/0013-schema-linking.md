# ADR 0013: Schema linking with lexical and embedding scores

- Status: Accepted
- Date: 2026-11-10

## Context

Sending every table, column and metric with every question wastes tokens, slows small local
models, and gives the model more ways to pick a wrong table. The demo schema has 9 tables, but a
customer's database can have hundreds. Only what a question needs should enter the prompt.

## Decision

1. **Two scores per table, metric and dimension.** A lexical hit: the name or a synonym appears in
   the question as whole words (case-insensitive, Unicode, plural `s` and the Indonesian
   possessive `-nya` stripped). An embedding score: the cosine between the question and the item's
   text (name, description, synonyms), embedded with the local `bge-m3`. The item score is the
   larger of the lexical hit (1.0) and the cosine when it is at least `SEMANTIC_MIN` (0.45).
2. **Metrics and dimensions pull their tables.** An item scoring at least `ITEM_MIN` (0.5) is
   "mentioned", and its tables (found by parsing its SQL) get 95% of its score. A metric built on
   another metric brings that metric along.
3. **Sample values count.** A sample value of an allowlisted column named in the question scores
   its table 0.7 ("di Bandung" finds `outlets`). Samples of omitted or sensitive columns are never
   used.
4. **Top tables, then bridges.** The best `DATA_LINK_TOP_TABLES` (4) tables are kept, then tables on
   the shortest path over foreign keys and semantic joins are added so the chosen set can be
   joined. A schema with at most that many tables is sent whole. With no positive score, the best
   cosines (or, without embeddings, the largest tables) are used.
5. **Degrades without embeddings.** If the embedding call fails or returns only zeros, linking is
   lexical only; a failure is not cached, so the next question tries again. The index is cached in
   the process per `(semantic_model_id, version)`.
6. **Ablation is a switch.** `schema_linking=False` sends every table, metric and dimension; the
   evaluation arm `no-linking` compares the two.

An embedding table in the database for these few dozen items was rejected: it would add a tenant
table and a re-index step for text that is cheap to embed once per process.

## Consequences

- Lexical-only linking is weak on free Indonesian: spot checks with the demo model missed
  "menguntungkan", "performa" and "stoknya" until synonyms and the `-nya` rule were added. Real
  deployments rely on the embeddings and on good synonyms in the semantic layer.
- `SEMANTIC_MIN` and `ITEM_MIN` are starting values, not calibrated. Calibrate them on the golden
  set (the report's `no-linking` arm shows what linking buys) before trusting them on other data.
- The cut at 4 tables can drop one a question needs; the bridge rule fixes missing joins, not
  missing facts. Raise `DATA_LINK_TOP_TABLES` for wide questions.
- Each API process embeds the semantic model once on first use, then keeps it in memory.
