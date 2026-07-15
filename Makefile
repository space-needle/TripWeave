COMPOSE_FILE := deploy/compose.local.yml
BACKEND_DIR := services/backend
WEB_DIR := apps/web

.PHONY: dev demo down logs format lint typecheck test build check generate-api-types seed-demo smoke e2e backup-restore-drill

dev:
	docker compose -f $(COMPOSE_FILE) up --build

demo:
	docker compose -f $(COMPOSE_FILE) up -d --build
	cd $(BACKEND_DIR) && uv run python ../../scripts/seed_demo.py

down:
	docker compose -f $(COMPOSE_FILE) down

logs:
	docker compose -f $(COMPOSE_FILE) logs -f

generate-api-types:
	cd $(BACKEND_DIR) && uv run python ../../scripts/generate_openapi_types.py

seed-demo:
	cd $(BACKEND_DIR) && uv run python ../../scripts/seed_demo.py

smoke:
	cd $(BACKEND_DIR) && uv run python ../../scripts/local_smoke.py

e2e:
	corepack pnpm --dir $(WEB_DIR) e2e

backup-restore-drill:
	./scripts/backup_restore_drill.sh

format:
	cd $(BACKEND_DIR) && uv run ruff format .
	corepack pnpm --dir $(WEB_DIR) format

lint:
	cd $(BACKEND_DIR) && uv run ruff check .
	corepack pnpm --dir $(WEB_DIR) lint

typecheck: generate-api-types
	cd $(BACKEND_DIR) && uv run mypy src tests
	corepack pnpm --dir $(WEB_DIR) typecheck

test:
	cd $(BACKEND_DIR) && uv run pytest
	corepack pnpm --dir $(WEB_DIR) test

build: generate-api-types
	corepack pnpm --dir $(WEB_DIR) build
	docker compose -f $(COMPOSE_FILE) build

check: format lint typecheck test build
