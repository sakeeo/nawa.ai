# Release checklist

Run this before declaring a phase released. Tick each item and record the date and commit.
Phase 0 acceptance (T0-21) uses the "Phase 0" items.

## Automated

- [ ] `cd apps/api && uv run pytest` with `TEST_DATABASE_OWNER_URL` set: zero skipped, zero failed.
- [ ] `make lint` clean (ruff, mypy, import-linter, eslint, tsc).
- [ ] `cd apps/web && pnpm test && pnpm build` clean.
- [ ] CI is green on the release branch.
- [ ] `make offline-smoke` passes: the local model answers and outbound access fails.

## Manual: clean install

- [ ] On a machine with no previous volumes: `cp .env.example .env`, set every secret, run `make dev`. The stack becomes healthy.
- [ ] The API log shows a one-time setup token. The setup wizard completes with it; the token is rejected afterwards.
- [ ] The wizard offers no external provider when `OFFLINE_MODE=true`.
- [ ] Sign in as the administrator.

## Manual: Phase 0 behaviour

- [ ] The administrator creates a workspace and invites a user; the invite link works once and expires.
- [ ] The invited user accepts, signs in, and sees only their workspace.
- [ ] A member of workspace A cannot read workspace B (API returns 403 or 404).
- [ ] AI settings page: one message through the gateway returns a reply.
- [ ] That call appears in Langfuse with prompt name and version, tokens, and cost.
- [ ] Demo data loads (`make seed`) and the August Bandung beef shortage is visible in the data.

## Release

- [ ] Documents match behaviour (see `docs/WORKFLOW.md` section 0.4).
- [ ] Feature branch merged into `master` with a merge commit.
- [ ] Version and commit hash recorded in `roadmap/PHASE <n> - <Name>/PROGRESS.md`.
