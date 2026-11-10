SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: dev dev-lite down seed test lint eval eval-experiments eval-report eval-sql eval-sql-experiments eval-sql-report offline-smoke

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

# Runs one experiment (NAME=chunking|retrieval|reranking|embedding|generator|all) from
# evals/experiments.yaml and saves JSON to evals/results/. Online, synthetic data only; takes
# hours on CPU for `all`, so run one at a time. The reranking experiment needs the reranker profile.
eval-experiments:
	mkdir -p evals/results && chmod a+rwx evals/results
	$(COMPOSE) run --rm \
		-e EVALS_DIR=/evals -e DEMO_DOCS_DIR=/app/seed/noesantara_docs -e GIT_COMMIT=$(shell git rev-parse --short HEAD) \
		-e RERANKER_TIMEOUT_SECONDS=$(or $(RERANK_TIMEOUT),180) \
		-v "$(CURDIR)/evals:/evals" -v "$(CURDIR)/seed/noesantara_docs:/app/seed/noesantara_docs:ro" \
		api python -m nawa.evaluation experiments --name $(or $(NAME),all) $(if $(LIMIT),--limit $(LIMIT))

# Renders docs/evaluation-report.md and docs/images/eval-*.svg from evals/results/.
eval-report:
	mkdir -p docs/images && chmod a+rwx docs docs/images
	$(COMPOSE) run --rm \
		-e EVALS_DIR=/evals -e DEMO_DOCS_DIR=/app/seed/noesantara_docs \
		-v "$(CURDIR)/evals:/evals:ro" -v "$(CURDIR)/seed/noesantara_docs:/app/seed/noesantara_docs:ro" \
		-v "$(CURDIR)/docs:/out" \
		api python -m nawa.evaluation report --output /out/evaluation-report.md

# Text-to-SQL evaluation (phase 2). `make eval-sql` runs the baseline arm of evals/sql_experiments.yaml
# against the demo database (run `make seed` first, with DEMO_DB_READONLY_PASSWORD set). Online,
# synthetic data only; needs Ollama (embeddings) and DEEPSEEK_API_KEY for the default generator.
# ARM=<name> and LIMIT=<n> are optional, e.g. `make eval-sql LIMIT=5`. Results go to evals/results/.
SQL_EVAL_MOUNTS = -e EVALS_DIR=/evals -e DEMO_SEMANTIC_YAML=/app/seed/noesantara_semantic.yaml \
	-e GIT_COMMIT=$(shell git rev-parse --short HEAD) \
	-v "$(CURDIR)/evals:/evals" -v "$(CURDIR)/seed/noesantara_semantic.yaml:/app/seed/noesantara_semantic.yaml:ro"

eval-sql:
	mkdir -p evals/results && chmod a+rwx evals/results
	$(COMPOSE) run --rm $(SQL_EVAL_MOUNTS) \
		api python -m nawa.evaluation sql --arm $(or $(ARM),baseline) $(if $(LIMIT),--limit $(LIMIT))

# Runs every arm (NAME=all) or one arm by name: baseline, no-linking, no-correction, gen-local.
eval-sql-experiments:
	mkdir -p evals/results && chmod a+rwx evals/results
	$(COMPOSE) run --rm $(SQL_EVAL_MOUNTS) \
		api python -m nawa.evaluation sql --arm $(or $(NAME),all) $(if $(LIMIT),--limit $(LIMIT))

# Renders docs/evaluation-report-sql.md from evals/results/sql-*.json; hand-written analysis is kept.
eval-sql-report:
	chmod a+rwx docs
	$(COMPOSE) run --rm $(SQL_EVAL_MOUNTS) -v "$(CURDIR)/docs:/out" \
		api python -m nawa.evaluation sql-report --output /out/evaluation-report-sql.md

offline-smoke:
	bash scripts/offline-smoke.sh
