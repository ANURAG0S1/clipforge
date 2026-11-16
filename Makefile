SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

API_DIR := apps/api
UV := cd $(API_DIR) && uv run

# The OpenAPI export only builds the app object; these values never reach a real service.
OPENAPI_ENV := DATABASE_URL=postgresql+asyncpg://x:x@localhost:5432/x REDIS_URL=redis://localhost:6379/0 \
	S3_ENDPOINT=http://localhost:9000 S3_PUBLIC_ENDPOINT=http://localhost:9000 \
	S3_ACCESS_KEY=x S3_SECRET_KEY=x S3_BUCKET=clipforge ANTHROPIC_API_KEY=sk-openapi-export \
	JWT_SECRET=openapi-export-only-not-a-real-secret-000

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install Python and Node dependencies
	cd $(API_DIR) && uv sync --frozen
	pnpm install --frozen-lockfile

.PHONY: env
env: ## Create .env from .env.example with a generated JWT secret (if .env is missing)
	@if [ -f .env ]; then echo ".env already exists"; else \
		sed "s|^JWT_SECRET=.*|JWT_SECRET=$$(openssl rand -hex 32)|" .env.example > .env; \
		echo "wrote .env; set ANTHROPIC_API_KEY before starting"; fi

# ---------- checks ----------
.PHONY: check
check: api-check web-check types-check ## Run every lint, type check and test (CI runs these)

.PHONY: api-check
api-check: ## ruff + mypy --strict + pytest
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy
	$(UV) pytest -q

.PHONY: web-check
web-check: ## eslint + prettier + tsc + vitest
	pnpm lint
	pnpm format:check
	pnpm typecheck
	pnpm test

.PHONY: types
types: ## Regenerate packages/shared-types from the FastAPI OpenAPI schema
	cd $(API_DIR) && $(OPENAPI_ENV) uv run python -m scripts.export_openapi ../../packages/shared-types/openapi.json
	pnpm --filter @clipforge/shared-types generate

.PHONY: types-check
types-check: types ## Fail if generated API types are out of date
	@git diff --quiet -- packages/shared-types || { \
		echo "packages/shared-types is stale: run 'make types' and commit the result"; \
		git --no-pager diff --stat -- packages/shared-types; exit 1; }

.PHONY: fmt
fmt: ## Auto-format Python and TS
	$(UV) ruff check --fix .
	$(UV) ruff format .
	pnpm format

# ---------- runtime ----------
.PHONY: up
up: ## Build and start the full stack, waiting until every service is healthy
	docker compose up -d --build --wait

.PHONY: down
down: ## Stop the stack (keeps volumes)
	docker compose down

.PHONY: logs
logs: ## Tail logs from all services
	docker compose logs -f --tail=100

.PHONY: migrate
migrate: ## Apply database migrations inside the stack
	docker compose run --rm migrate

.PHONY: migration
migration: ## Autogenerate a migration: make migration m="add foo"
	@test -n "$(m)" || { echo 'usage: make migration m="message"'; exit 1; }
	docker compose run --rm --no-deps migrate alembic revision --autogenerate -m "$(m)"

.PHONY: health
health: ## Query the API health endpoint
	@curl -fsS http://localhost:8000/healthz | python3 -m json.tool
