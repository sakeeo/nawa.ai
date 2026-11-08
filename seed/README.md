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

The ~30 demo documents (kitchen and food-safety SOPs, goods-receiving SOP, complaint and
refund policy, HR policy, supplier contracts, monthly reports, and two prompt-injection
documents) are added at the start of Phase 1.
