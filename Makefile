COMPOSE_FILE := deploy/compose.local.yml
BACKEND_DIR := services/backend
WEB_DIR := apps/web

.PHONY: dev down logs format lint typecheck test build check

dev:
	docker compose -f $(COMPOSE_FILE) up --build

down:
	docker compose -f $(COMPOSE_FILE) down

logs:
	docker compose -f $(COMPOSE_FILE) logs -f

format:
	cd $(BACKEND_DIR) && uv run ruff format .
	corepack pnpm --dir $(WEB_DIR) format

lint:
	cd $(BACKEND_DIR) && uv run ruff check .
	corepack pnpm --dir $(WEB_DIR) lint

typecheck:
	cd $(BACKEND_DIR) && uv run mypy src tests
	corepack pnpm --dir $(WEB_DIR) typecheck

test:
	cd $(BACKEND_DIR) && uv run pytest
	corepack pnpm --dir $(WEB_DIR) test

build:
	corepack pnpm --dir $(WEB_DIR) build
	docker compose -f $(COMPOSE_FILE) build

check: format lint typecheck test build
