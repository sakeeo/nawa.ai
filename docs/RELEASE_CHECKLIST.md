# Release checklist

Run this before declaring a phase released. Tick each item and record the date and commit.
Phase 0 acceptance (T0-21) uses the "Phase 0" items.

## Automated

- [x] `cd apps/api && uv run pytest` with `TEST_DATABASE_OWNER_URL` set: zero skipped, zero failed. (2026-11-08, 64900ea: 167 passed)
- [x] `make lint` clean (ruff, mypy, import-linter, eslint, tsc). (2026-11-08, 64900ea)
- [x] `cd apps/web && pnpm test && pnpm build` clean. (2026-11-08, 64900ea: 9 passed)
- [ ] CI is green on the release branch.
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

- [ ] Documents match behaviour (see `docs/WORKFLOW.md` section 0.4).
- [ ] Feature branch merged into `master` with a merge commit.
- [ ] Version and commit hash recorded in `roadmap/PHASE <n> - <Name>/PROGRESS.md`.
