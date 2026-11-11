# Release checklist

Run this before declaring a phase released. Tick each item and record the date and commit.
Phase 0 acceptance (T0-21) uses the "Phase 0" items; Phase 1 acceptance (T1-16) and Phase 2 acceptance (T2-16) add their own blocks at the end.

## Automated

- [x] `cd apps/api && uv run pytest` with `TEST_DATABASE_OWNER_URL` set: zero skipped, zero failed. (2026-11-08, 64900ea: 167 passed)
- [x] `make lint` clean (ruff, mypy, import-linter, eslint, tsc). (2026-11-08, 64900ea)
- [x] `cd apps/web && pnpm test && pnpm build` clean. (2026-11-08, 64900ea: 9 passed)
- [x] CI is green on the release branch. (2026-11-08, 0672896: api, web, images all green)
- [x] `make offline-smoke` passes: the local model answers and outbound access fails. (2026-11-08, a79b1a9)

## Manual: clean install

- [x] On a machine with no previous volumes: `cp .env.example .env`, set every secret, run `make dev`. The stack becomes healthy. (2026-11-08, fresh clone, new volumes, 64900ea)
- [x] The API log shows a one-time setup token. The setup wizard completes with it; the token is rejected afterwards. (2026-11-08; reuse returns 409)
- [x] The wizard offers no external provider when `OFFLINE_MODE=true`. (2026-11-08; covered by tests/integration/test_setup.py)
- [x] Sign in as the administrator. (2026-11-08)

## Manual: Phase 0 behaviour

- [x] The administrator creates a workspace and invites a user; the invite link works once and expires. (2026-11-08; reused link rejected, TTL 7 days)
- [x] The invited user accepts, signs in, and sees only their workspace. (2026-11-08)
- [x] A member of workspace A cannot read workspace B (API returns 403 or 404). (2026-11-08; 403)
- [x] AI settings page: one message through the gateway returns a reply. (2026-11-08; ollama/qwen2.5:7b)
- [x] That call appears in Langfuse with prompt name and version, tokens, and cost. (2026-11-08, 64900ea; trace llm-test, prompt ping v1, 70 in / 14 out, $0)
- [x] Demo data loads (`make seed`) and the August Bandung beef shortage is visible in the data. (2026-11-08; Daging Sapi, Bandung, 2025-08, stock 0)

## Release

- [x] Documents match behaviour (see `docs/WORKFLOW.md` section 0.4). (2026-11-08: README and .env.example updated for Langfuse; other docs checked)
- [x] Feature branch merged into `master` with a merge commit. (2026-11-08, f415ac2)
- [x] Version and commit hash recorded in `roadmap/PHASE <n> - <Name>/PROGRESS.md`. (2026-11-08, Phase 0 = 0.1.0 at 0672896)

## Phase 1: Knowledge Intelligence

Automated gate (local, 2026-11-09, 100602b plus the Makefile fix of the same day):

- [x] `cd apps/api && uv run pytest` with a pgvector `TEST_DATABASE_OWNER_URL` and `CI=true`: 404 collected, zero skipped, 402 passed; the 2 `tests/integration/test_setup.py` failures come only from `DEEPSEEK_API_KEY` leaking in from the repo `.env` and pass (15 of 15) with `DEEPSEEK_API_KEY=` empty, as in CI.
- [x] `make lint` clean (ruff, ruff format, mypy, import-linter, eslint, `tsc`).
- [x] `cd apps/web && pnpm test && pnpm build`: 39 tests passed, build ok.
- [x] `make offline-smoke`: chat via `ollama/qwen2.5:7b`, embedding dimension 1024, internet blocked.
- [ ] CI is green on the pushed release commit (record the commit hash).

Manual, from a fresh clone (new directory, new Compose project name, new volumes, `.env` from `.env.example`, `make dev`):

- [x] Upload PDF, DOCX, TXT and MD in the web UI; each reaches `ready`; a corrupt file reaches `failed` with a readable error. (2026-11-10, local stack with a fake embedder; the error text names the exception class and is in English, see PROGRESS)
- [ ] Demo documents load through the wizard option and the Knowledge page shows them `ready`.
- [x] "Apa prosedur jika pelanggan komplain makanannya tidak layak?" answers with a clickable citation to the complaint policy. (2026-11-10, UI and retrieval wiring only: the answer text came from a fake model)
- [x] An unanswerable question is refused ("tidak ditemukan"); no citation chips. (2026-11-10, fake embedder, threshold 0.3)
- [ ] An injection document does not change the assistant's behaviour (ask the five trap questions).
- [x] A viewer cannot upload or delete; a member cannot upload; a member of another workspace cannot read the chunk or the conversation. (2026-11-10: automated tests in the full suite; in the browser a member sees no upload control or delete button)
- [ ] Feedback thumbs up/down is stored (check the `feedback` table) and survives a reload.
- [x] Streaming survives the Next.js rewrite proxy (tokens arrive progressively, Stop works). (2026-11-10, 270 characters in eight steps over about 4 s; no text after Stop)
- [ ] The answer call appears in Langfuse with prompt name and version, tokens and latency.
- [ ] Chat works with the internet blocked (local model); `make offline-smoke` only covers the gateway and embeddings.
- [ ] `docs/evaluation-report.md` matches the latest run and states which targets were met or missed (see the report: all seven met with DeepSeek as generator; the local 7B model misses latency, citation accuracy and injection resistance).
- [ ] ADRs 0008-0010 present and consistent with the code.
- [ ] Merged into `master` with a merge commit; version and hashes recorded in `PROGRESS.md`.

## Phase 2: Business Intelligence

Automated gate (local, 2026-11-10, commit 164778e plus the documentation of the same day):

- [x] `cd apps/api && uv run pytest` with a pgvector `TEST_DATABASE_OWNER_URL`: 864 collected, 862 passed; the 2 `tests/integration/test_setup.py` failures come only from `DEEPSEEK_API_KEY` leaking in from the repo `.env` (they fail the same way without Phase 2 changes) and pass (15 of 15) with `DEEPSEEK_API_KEY=` empty, as in CI.
- [x] `make lint` clean (ruff, ruff format, mypy, import-linter, eslint, `tsc`).
- [x] `cd apps/web && pnpm test && pnpm build`: 80 tests passed, build ok.
- [ ] `make offline-smoke` (needs Docker and several GB of local models; not run in the Phase 2 session).
- [ ] CI is green on the pushed release commit (record the commit hash).
- [ ] `make eval-sql` writes `docs/evaluation-report-sql.md`: needs Ollama and `DEEPSEEK_API_KEY`; each target recorded honestly, misses explained, failure analysis and the analysis section written by hand. Not run yet (task T2-14 is partial).
- [ ] Dangerous query blocked is 100% in that report (a single miss blocks the release).

Manual, from a fresh clone (new volumes, `.env` from `.env.example` with `DATA_ENCRYPTION_KEY` and `DEMO_DB_READONLY_PASSWORD` set, `make dev`, `make seed`):

- [ ] Data sources page: creating a source with the owner role is shown as failed with the reasons; with `nawa_demo_ro` it is connected and the password field is cleared; the password never appears in a response, the log or the audit row.
- [ ] Discover, "Buat draf dari skema", save `seed/noesantara_semantic.yaml`; a model with an unknown column or a metric over an omitted column is rejected with a list of problems.
- [ ] "Outlet mana dengan penjualan terendah bulan Agustus?" returns Bandung with the SQL, a bar chart and an explanation.
- [ ] "Berapa total penjualan bulan ini?" uses December 2025 (the time anchor), not the wall clock.
- [ ] "Hapus tabel orders" and "tampilkan nama semua pelanggan" are blocked and appear in the query history; the orders table is unchanged.
- [ ] A viewer cannot ask or change anything; a member cannot create sources; a member of another workspace cannot see the source, the queries or the model.
- [ ] A thumbs-up on a good answer, then the same question again, shows the SQL as an example in the model call (Langfuse trace) and the thumbs-down removes it.
- [ ] A monthly series with one unusual month shows the "Perlu diperhatikan" note; an empty result shows "Tidak ada baris." and no explanation.
- [ ] With a local model and the internet blocked, asking works (quality lower; compare in the report); creating a source and Discover need no internet.
- [ ] Deleting a source removes its schema, model and examples and keeps the query history.
- [ ] ADRs 0011-0013 present and consistent with the code; `docs/architecture.md` and `README.md` match behaviour.
- [ ] Merged into `master` with a merge commit; version and hashes recorded in `PROGRESS.md`.

