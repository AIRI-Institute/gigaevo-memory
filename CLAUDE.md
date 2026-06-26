# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

GigaEvo Memory is a persistent memory subsystem for CARL artifacts (steps, chains, agents, agent skills, memory cards). It consists of two Python packages managed as a `uv` workspace:

- `api/` (`gigaevo-memory-api`) — FastAPI service, async SQLAlchemy + asyncpg, Alembic migrations, Redis pub/sub.
- `web_ui/` (`gigaevo-memory-web-ui`) — Gradio frontend that talks to the API over HTTP.

The public Python SDK (`gigaevo-client`, importable as `gigaevo_client`) lives in its **own repository** and is consumed here from PyPI — both `api` and `web_ui` declare it as a normal dependency. It used to live under `client/python/` in this repo (with a `gigaevo-memory` legacy import shim); that source has since been extracted, so client building/publishing no longer happens here.

Python 3.12+. Workspace root `pyproject.toml` aggregates both members.

## Commands

All routine workflows go through the top-level `Makefile`. The Compose project name is `gigaevo-memory`, file `deploy/docker-compose.yml`.

### Docker stack
- `make up` — start the full stack (auto-applies Alembic migrations first).
- `make stop` / `make down` / `make restart` / `make rebuild` / `make rebuild-logs` (alias `make rl`).
- `make logs s=memory-api` — follow logs for one service (alias `make l`).
- `make psql` / `make redis-cli` — shell into the internal services.
- Published ports default to API `8002` and Web UI `7861` (containers listen on `8000` / `7860`). Override via `MEMORY_API_HOST_PORT` / `MEMORY_WEB_UI_HOST_PORT` in `deploy/.env`.

### Migrations
- `make migrate` — `alembic upgrade head` inside the `memory-migrate` service.
- `make migrate-create m="description"` — autogenerate a new revision.
- `make migrate-down` — downgrade one step.
- `make migrate-check` — runs the same `pytest tests/test_migration_chain.py` + `upgrade head → downgrade -1 → upgrade head` round-trip as the `migration-safety` GitHub Action (`.github/workflows/migration-safety.yml`). **Run this before merging any change under `api/app/db/migrations/` or `api/app/db/models.py`** — CI will reject revisions that can't round-trip.
- `make db-reset` — interactive (confirms): drops and recreates `public` schema, then migrates.

### Testing
- `make test` — fast API unit tests (no Docker); alias for `make test-api-unit`.
- `make test-api-unit` — fast API unit subset (explicit file list in the Makefile target — when adding new unit tests that should run without Docker, add them there). This is the slice the `CI` GitHub Action (`.github/workflows/ci.yml`) runs.
- `make test-api-all` — full API suite inside Compose (`memory-api-test` service, profile `test`).
- `make test-integration` — only tests marked `@pytest.mark.integration` (registered in `api/pytest.ini`).
- Single test: `cd api && uv run pytest tests/test_entity_service.py::test_name -v`.

### Lint / format
- `make lint` — `ruff check` over `api/app/`.
- `make fmt` — `ruff format` (line length 120, set at workspace root).

### Operational
- `make openapi` — regenerate `openapi.yaml` from the running FastAPI app.
- `make backup` / `make backup-dry-run` — `pg_dump` to `./backups/`, optional S3 upload via `S3_BUCKET=...`. See `deploy/scripts/backup.sh`.
- `make create-key OWNER=alice [SCOPES=read:any,evolve] [LABEL="..."] [EXPIRES_DAYS=30]` — issues an API key. **The plaintext is printed exactly once**; the DB only stores the SHA-256 hash (`api/app/services/api_key_service.py`, CLI in `api/app/create_key.py`).

### Standalone (no Compose)
- `make local-db` / `local-redis` / `local-api` / `local-ui` / `local-start` / `local-stop` / `local-status` — run Postgres + Redis in plain `docker run` and uvicorn/Gradio directly on the host. Default ports differ from Compose: API `8000`, UI `7860`, DB user/db `gigaevo`. Don't mix the two modes — they collide on container names and the DSN differs.

## Architecture

### Entity model
Two-table core (`api/app/db/models.py`):
- `entities` — stable identity (`entity_id`, `entity_type`, `namespace`, `name`, `tags`, `channels` dict, library metadata `favourite`/`run_count`/`last_run_at`/`display_name`/`description`, full-text `search_vector`).
- `entity_versions` — immutable content snapshots (`content_json`, `meta_json`, `parents`, `evolution_meta`). Channels (`latest`, `stable`, custom) are pointers from `entities.channels` to a `version_id`.
- `entity_search_documents` — derived per-version, per-`document_kind` rows powering BM25 + vector search. Always rebuilt from `EntityVersion` via `search_document_service.sync_entity_search_documents` — do not write to this table directly outside that service.

Five entity types (singular ↔ plural mapped in `VALID_ENTITY_TYPES` in `api/app/services/entity_service.py`): `step`/`steps`, `chain`/`chains`, `agent`/`agents`, `agent_skill`/`agent_skills`, `memory_card`/`memory_cards`.

ETags are SHA-256 of canonical-JSON `content_json` (`compute_etag`). Cursor pagination is base64-encoded JSON `{v, created_at, entity_id, entity_type, channel}` (`_encode_cursor`/`_decode_cursor`).

### Router layout (`api/app/main.py`)
- Typed routers (recommended): `steps`, `chains`, `agents`, `agent_skills`, `memory_cards` — mounted at root (each declares its own `/v1/...` prefix).
- `entities` — generic CRUD, mounted at `/v1`, kept for back-compat (tagged `entities (deprecated)`). New work should add typed endpoints alongside the existing four, not extend `entities.py`.
- `bulk` (`/v1/bulk/...`) — consumed by `care import`.
- `versions` (`/v1/...`) — version history, diffs, lineage, channel pinning.
- `unified_search` + `embeddings` + `events` — search & SSE.
- `health` — no prefix.

### Auth (`api/app/auth.py`)
Single dependency `require_api_key` → `AuthContext`. Dual-mode driven by `settings.auth_required`:
- **Opt-in** (`AUTH_REQUIRED=false`, dev/CI default): missing header → anonymous `AuthContext(owner="anonymous", scopes=set())`. Invalid/revoked/expired keys still 401.
- **Strict** (`AUTH_REQUIRED=true`, production): missing header also 401.

Scopes are `namespace:action`. Canonical constants live in `auth.py`: `SCOPE_READ_ANY`, `SCOPE_WRITE_ANY`, `SCOPE_DELETE_ANY`, `SCOPE_CLEAR_ALL`, `SCOPE_ADMIN_KEYS`, `SCOPE_EVOLVE`. Default namespace for a write is the caller's `owner` — use the `default_namespace_for` / `default_read_namespace_for` helpers when adding endpoints so cross-namespace access remains gated by `read:any` / `write:any`.

### Search
Strategy pattern (`api/app/services/search_strategies/`): `BM25SearchStrategy`, `VectorSearchStrategy`, `HybridSearchStrategy`, dispatched by `UnifiedSearchService` based on `SearchType`. Vector search requires `ENABLE_VECTOR_SEARCH=true` and a Postgres with `pgvector` (the Compose image is `pgvector/pgvector:pg16`). A pluggable `Reranker` runs after retrieval — configure via `RERANKER_KIND` (default `"identity"`); register new implementations through `RerankerRegistry`.

### Events
`api/app/events/publisher.py` publishes JSON to Redis channel `memory:events` on every entity mutation, including `namespace` and `tags` so SSE subscribers can filter without re-fetching. The `/v1/events` SSE forwarder applies backpressure: subscribers lagging more than `SSE_WARN_LAG_SECONDS` (10s default) get a `lag_warning` injected; past `SSE_DROP_LAG_SECONDS` (60s default) they are disconnected.

### Configuration (`api/app/config.py`)
All settings are env-driven via `pydantic-settings` (`env_prefix=""`, case-insensitive). Notable knobs: `POSTGRES_DSN`, `REDIS_URL`, `ENABLE_VECTOR_SEARCH`, `EMBEDDING_PROVIDER` (`sentencetransformers`/`openai`/`huggingface`), `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `AUTH_REQUIRED`, `RERANKER_KIND`, hybrid weight defaults.

## Conventions

### CARE chain content
Chains store opaque JSON; the canonical convention for `content["metadata"]` (used by CARE TUI, MAGE generator, evolution platform) is documented in `docs/CHAIN_CONTENT_CONVENTIONS.md`. Helpers `CareChainMetadata.merge_into_content()` / `.from_chain_content()` live in both the API request models and the client SDK — reuse them rather than hand-rolling the dict. On save, CARE writes both `Entity.display_name` (mutable, indexed) and `metadata.display_name` (content-embedded). On read, the DB column is authoritative.

### Client SDK imports
The SDK package is `gigaevo_client` (consumed from PyPI; source lives in its own repo). When this codebase touches the client — e.g. `web_ui/app/client.py` — import from `gigaevo_client`, never the legacy `gigaevo_memory` shim. `api/tests/test_no_legacy_gigaevo_memory_imports.py` enforces that the **server** never imports the legacy shim.
