SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: dev dev-lite down seed test lint eval offline-smoke

dev:
	@test -f .env || (echo "Missing .env: copy .env.example and set secrets" && exit 1)
	$(COMPOSE) --profile observability up -d --build

dev-lite:
	@test -f .env || (echo "Missing .env: copy .env.example and set secrets" && exit 1)
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) --profile observability --profile local-llm down

seed:
	$(COMPOSE) run --rm --no-deps api python -m nawa.workspace.demo

test:
	cd apps/api && uv run pytest
	cd apps/web && pnpm test

lint:
	cd apps/api && uv run ruff check . ../../seed && uv run ruff format --check . ../../seed && uv run mypy && uv run lint-imports
	cd apps/web && pnpm lint && pnpm typecheck

# Runs the golden dataset against the default config inside the api image. Needs the stack's
# database and Ollama (embeddings) plus DEEPSEEK_API_KEY for the judge; refuses to run offline.
# CONFIG=<name|path> and LIMIT=<n> are optional, e.g. `make eval CONFIG=default LIMIT=5`.
eval:
	$(COMPOSE) run --rm \
		-e EVALS_DIR=/evals -e DEMO_DOCS_DIR=/app/seed/noesantara_docs \
		-v "$(CURDIR)/evals:/evals:ro" -v "$(CURDIR)/seed/noesantara_docs:/app/seed/noesantara_docs:ro" \
		api python -m nawa.evaluation run --config $(or $(CONFIG),default) $(if $(LIMIT),--limit $(LIMIT))

offline-smoke:
	./scripts/offline-smoke.sh
