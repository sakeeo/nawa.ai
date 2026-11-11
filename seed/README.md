# Demo seed: Resto Noesantara (fictional)

Deterministic synthetic data used by the demo and the evaluation suite.

Resto Noesantara is a fictional Indonesian restaurant chain: 5 outlets, 72 menu items,
16 ingredients with per-dish recipes, 500 loyalty members, one year of orders across
dine-in, takeaway, and delivery channels, monthly ingredient stock, and expenses.

- `noesantara_seed/generate.py` builds the dataset in memory (seed 42, year 2025).
- `noesantara_seed/load.py` recreates the tables in the `noesantara` database and bulk-loads them.
- Run inside the stack: `make seed`.

Planted anomaly: in August 2025 the beef supplier fails to deliver to the Bandung outlet.
Beef stock is zero, all 12 beef dishes are unavailable, and the outlet's sales drop by
about 30%. Phases 2 and 3 use this story.

## Demo documents (`noesantara_docs/`)

34 Indonesian documents of the fictional Resto Noesantara: kitchen and food-safety SOPs,
goods-receiving SOPs, complaint and refund policy (including the "makanan tidak layak"
procedure used by the demo story), HR policy, supplier contracts, monthly outlet reports whose
figures are computed from the seed, a table-heavy menu guide, a very long handbook, and two
prompt-injection memos (`injection-*.md`). Formats are mostly `.md`, with `.txt`, `.docx` and
`.pdf` to exercise every extractor.

- `scripts/generate-demo-docs.py` wrote them with DeepSeek (synthetic data only, manual run,
  refuses `OFFLINE_MODE=true`). Every file was then reviewed by hand.
- `MANIFEST.yaml` is the contract: per file `filename`, `title`, `kind`, `language`, `sha256`
  and `facts`. The facts come from the generator briefs, not from model output.
- **The documents are fixtures.** Regenerating them changes the golden dataset (T1-13), so do
  not regenerate; after a hand edit run the script with `--manifest-only` to refresh hashes.
- The golden dataset `evals/golden.yaml` (75 questions) points at these files and at fact ids
  `<filename>#<index>` in the manifest; `make eval` and the experiments ingest them into the
  `nawa-eval` workspace.

## Data analyst (`noesantara_semantic.yaml`)

The Phase 2 data analyst queries the `noesantara` database as a SELECT-only role.

- `make seed` creates that role (`DEMO_DB_READONLY_USER`, password `DEMO_DB_READONLY_PASSWORD`; skipped
  when the password is empty) after every load, because reloading drops the tables and their grants.
  `seed_load.ensure_readonly_role(url, role, password)` is idempotent.
- `noesantara_semantic.yaml` is the semantic layer to paste into the Data sources page: nine tables,
  the metrics `revenue`, `gross_profit`, `order_count`, `average_order_value`, `units_sold` and
  `total_expenses`, seven dimensions, the joins, Indonesian synonyms, and a `time_anchor` so that
  "bulan ini" means December 2025, the month of the newest order. `customers.name` is left out on
  purpose: it is personal data the analyst must not read.
- The golden dataset `evals/sql_golden.yaml` (50 answerable questions with hand-checked reference SQL,
  10 dangerous ones) is written against this exact data. The reference answers are pinned by
  `tests/integration/test_sql_golden_reference.py`; if the generator changes, that test fails and the
  dataset must be re-checked, so do not change the generator casually.

