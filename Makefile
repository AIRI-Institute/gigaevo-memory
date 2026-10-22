COMPOSE := docker compose -p gigaevo-memory -f deploy/docker-compose.yml
COMPOSE_TEST := docker compose -p gigaevo-memory-test -f deploy/docker-compose.yml --profile test
UV := uv

.PHONY: up stop down restart rebuild rebuild-logs rl build logs migrate migrate-down migrate-create migrate-check db-reset \
        test test-api-unit test-api-all test-integration lint fmt openapi \
        psql redis-cli seed create-key backup backup-dry-run clean help \
        web-ui-logs web-ui-build web-ui-reload \
        local-db local-redis local-api local-ui local-start local-stop local-status

up: ## Start the stack (memory-api + postgres + redis + web-ui)
	$(COMPOSE) up -d

stop: ## Stop containers without removing them
	$(COMPOSE) stop

down: ## Stop and remove containers
	$(COMPOSE) down

restart: ## Restart services (down + up)
	$(MAKE) down
	$(MAKE) up

rebuild: ## Rebuild all images and restart (build + down + up)
	$(COMPOSE) build --no-cache
	$(COMPOSE) down
	$(COMPOSE) up -d

rebuild-logs: ## Rebuild and show logs (rebuild + logs)
	$(MAKE) rebuild
	$(MAKE) logs

build: ## Build Docker images without cache
	$(COMPOSE) build --no-cache

logs: ## View logs from all containers (optionally: make logs s=memory-api)
	$(COMPOSE) logs -f $(s)

migrate: ## Apply Alembic migrations (up to head)
	$(COMPOSE) run --rm memory-migrate

migrate-down: ## Rollback last migration
	$(COMPOSE) run --rm memory-migrate alembic -c app/db/alembic.ini downgrade -1

migrate-create: ## Create new migration (make migrate-create m="description")
	$(COMPOSE) run --rm memory-migrate alembic -c app/db/alembic.ini revision --autogenerate -m "$(m)"

migrate-check: ## Validate migration chain + alembic upgrade/downgrade round-trip (matches CI gate)
	@echo "🧪 Static migration chain integrity (no DB)..."
	cd api && $(UV) run pytest tests/test_migration_chain.py -v
	@echo "🧪 alembic upgrade head (clean DB → head)..."
	$(COMPOSE) run --rm memory-migrate alembic -c app/db/alembic.ini upgrade head
	@echo "🧪 alembic downgrade -1..."
	$(COMPOSE) run --rm memory-migrate alembic -c app/db/alembic.ini downgrade -1
	@echo "🧪 alembic upgrade head (re-apply)..."
	$(COMPOSE) run --rm memory-migrate alembic -c app/db/alembic.ini upgrade head
	@echo "✅ Migration round-trip OK"

db-reset: ## Reset database (drop all tables and re-run migrations)
	@echo "⚠️  This will delete all data in the database!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo "🗑️  Dropping all tables..."; \
		$(COMPOSE) exec -T postgres psql -U memory -d memory -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"; \
		echo "🔄 Running migrations..."; \
		$(MAKE) migrate; \
		echo "✅ Database reset complete!"; \
	else \
		echo "❌ Aborted"; \
	fi

test: ## Run all API tests
	@echo "🧪 Running all tests..."
	$(MAKE) test-api-unit

test-integration: ## Run API integration tests (with dependencies)
	$(COMPOSE_TEST) run --build --rm memory-api-test sh -lc "alembic -c app/db/alembic.ini upgrade head && python -m pytest -m integration"

test-api-unit: ## Run API unit tests (no Docker required)
	@echo "🧪 Running API unit tests..."
	cd api && uv run --with pytest --with pytest-asyncio --with respx --with httpx python -m pytest tests/test_entity_service.py tests/test_embedding_service.py tests/test_vector_utils.py tests/test_health.py::TestHealthUnit tests/test_embeddings.py::TestEmbeddingsRequestResponse tests/test_embeddings.py::TestEmbeddingsEndpointUnit tests/test_events.py::TestEventPublisherUnit -v -W ignore::pytest.PytestConfigWarning

test-api-all: ## Run all API tests (unit + integration with Docker)
	@echo "🧪 Running all API tests..."
	$(COMPOSE_TEST) down -v --remove-orphans
	$(COMPOSE_TEST) run --build --rm memory-api-test sh -lc "alembic -c app/db/alembic.ini upgrade head && python -m pytest"

lint: ## Lint code (ruff)
	cd api && ruff check app/

fmt: ## Auto-format code (ruff format)
	cd api && ruff format app/

openapi: ## Generate/update openapi.yaml from FastAPI
	$(COMPOSE) run --rm memory-api python -c \
		"import json, yaml; from app.main import app; print(yaml.dump(app.openapi()))" > openapi.yaml

psql: ## Interactive psql session
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-memory} -d $${POSTGRES_DB:-memory}

redis-cli: ## Interactive redis-cli session
	$(COMPOSE) exec redis redis-cli

seed: ## Load test data fixtures
	$(COMPOSE) run --rm memory-api python -m app.seed

create-key: ## Issue an API key (make create-key OWNER=alice [SCOPES=read:any,evolve] [LABEL="..."] [EXPIRES_DAYS=30])
	@if [ -z "$(OWNER)" ]; then echo "error: OWNER is required (e.g. make create-key OWNER=alice)" >&2; exit 2; fi
	$(COMPOSE) run --rm \
		-e OWNER='$(OWNER)' \
		-e SCOPES='$(SCOPES)' \
		-e LABEL='$(LABEL)' \
		-e EXPIRES_DAYS='$(EXPIRES_DAYS)' \
		memory-api python -m app.create_key

backup: ## Dump Postgres to ./backups (optionally upload to S3 via S3_BUCKET=...)
	deploy/scripts/backup.sh

backup-dry-run: ## Show the commands `make backup` would run, without executing them
	deploy/scripts/backup.sh --dry-run

web-ui-logs: ## View web-ui logs
	$(COMPOSE) logs -f web-ui

web-ui-build: ## Rebuild web-ui image
	$(COMPOSE) build web-ui

web-ui-reload: ## Rebuild and restart web-ui (required for code changes)
	$(COMPOSE) build web-ui
	$(COMPOSE) up -d web-ui

# Local development (without Docker Compose)

local-db: ## Start local PostgreSQL in Docker
	@docker rm -f postgres-gigaevo 2>/dev/null || true
	docker run -d --name postgres-gigaevo \
		-e POSTGRES_DB=gigaevo \
		-e POSTGRES_USER=gigaevo \
		-e POSTGRES_PASSWORD=gigaevo \
		-p 5432:5432 \
		postgres:15-alpine
	@echo "✅ PostgreSQL started on localhost:5432"
	@sleep 3
	@docker exec postgres-gigaevo pg_isready -U gigaevo && echo "✅ PostgreSQL is ready"

local-redis: ## Start local Redis in Docker
	@docker rm -f redis-gigaevo 2>/dev/null || true
	docker run -d --name redis-gigaevo \
		-p 6379:6379 \
		redis:7-alpine
	@echo "✅ Redis started on localhost:6379"

local-api: ## Start API server locally (requires local-db)
	@uv sync --no-dev && \
	cd api && \
	if [ -f "alembic.ini" ]; then uv run alembic upgrade head; fi && \
	DATABASE_URL="postgresql://gigaevo:gigaevo@localhost:5432/gigaevo" \
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

local-ui: ## Start Web UI locally
	@uv sync --no-dev && \
	cd web_ui && \
	MEMORY_API_URL=http://localhost:8000 \
	uv run python -m app.main

local-start: ## Start full local stack (db + api + ui)
	@echo "🚀 Starting local development stack..."
	$(MAKE) local-db
	$(MAKE) local-redis
	@echo "Starting API in background..."
	@$(MAKE) local-api > logs/api.log 2>&1 &
	@sleep 5
	@echo "Starting Web UI in background..."
	@$(MAKE) local-ui > logs/ui.log 2>&1 &
	@sleep 3
	@echo ""
	@echo "✅ Stack started!"
	@echo "   API:    http://localhost:8000"
	@echo "   UI:     http://localhost:7860"
	@echo "   Logs:   logs/api.log, logs/ui.log"
	@echo ""
	@echo "Run 'make local-stop' to stop all services"

local-stop: ## Stop local services
	@echo "🛑 Stopping local services..."
	@pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@pkill -f "python -m app.main" 2>/dev/null || true
	@docker stop postgres-gigaevo redis-gigaevo 2>/dev/null || true
	@echo "✅ All services stopped"

local-status: ## Check local services status
	@echo "🔍 Local Services Status"
	@echo "========================"
	@echo ""
	@echo "PostgreSQL:"
	@docker ps -f name=postgres-gigaevo --format "  Status: {{.Status}}" 2>/dev/null || echo "  ❌ Not running"
	@echo ""
	@echo "Redis:"
	@docker ps -f name=redis-gigaevo --format "  Status: {{.Status}}" 2>/dev/null || echo "  ❌ Not running"
	@echo ""
	@echo "API (port 8000):"
	@curl -s http://localhost:8000/health > /dev/null 2>&1 && echo "  ✅ Running" || echo "  ❌ Not running"
	@echo ""
	@echo "Web UI (port 7860):"
	@curl -s http://localhost:7860 > /dev/null 2>&1 && echo "  ✅ Running" || echo "  ❌ Not running"

clean: ## Remove containers, volumes, and generated files
	$(COMPOSE) down -v --remove-orphans
	@docker rm -f postgres-gigaevo redis-gigaevo 2>/dev/null || true

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | sort | awk 'BEGIN {FS = ":.*?## "}; {printf " \033[36m%-20s\033[0m %s\n", $$1, $$2}'

rl: rebuild-logs
l: logs
