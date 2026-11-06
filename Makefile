SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: dev dev-lite down seed test lint eval

dev:
	@test -f .env || (echo "Missing .env: copy .env.example and set secrets" && exit 1)
	$(COMPOSE) --profile observability up -d --build

dev-lite:
	@test -f .env || (echo "Missing .env: copy .env.example and set secrets" && exit 1)
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) --profile observability --profile local-llm down

seed:
	@echo "seed: implemented in Phase 0 slice D"

test:
	cd apps/api && uv run pytest
	cd apps/web && pnpm test

lint:
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports
	cd apps/web && pnpm lint && pnpm typecheck

eval:
	@echo "eval: implemented in Phase 1"
