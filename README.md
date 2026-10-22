# GigaEvo Memory - Memory Subsystem for the Evolution Process

Persistent memory for CARL artifacts: steps, chains, agents, and memory cards.

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- GNU Make
- Python 3.10+ and `uv` for standalone local development

### Starting the Docker Stack

```bash
make up
# Pause the stack without removing containers
make stop
```

`make up` now automatically applies Alembic migrations before starting the API. The `make migrate` command is still available if you want to run a schema update explicitly.

### Access Points

- API: `http://localhost:8002`
- Swagger UI: `http://localhost:8002/docs`
- Web UI: `http://localhost:7861`

The default compose deployment only publishes the API and Web UI. PostgreSQL and Redis remain internal to the Docker network. Use `make psql` or `make redis-cli` if you need shell access to those services.

### Overriding Published Ports

Set these variables in `deploy/.env` or export them before running `make up`:

```bash
MEMORY_API_HOST_PORT=8002
MEMORY_WEB_UI_HOST_PORT=7861
```

### Standalone Local Development

Standalone API and UI runs keep their original defaults unless you explicitly override them:

- API client documentation examples may use `http://localhost:8000`
- The standalone Gradio UI process defaults to `http://localhost:7860`

These standalone defaults are independent of the Docker Compose stack described above.

## 📚 Features

### Entity Types

- **Steps** — Individual reasoning steps (LLM, Tool, MCP, Memory, Transform, Condition)
- **Chains** — Sequences of steps with dependencies
- **Agents** — Complete agent configurations
- **Agent Skills** — Portable SKILL.md bundles (see [`docs/AGENT_SKILL_ENTITY.md`](docs/AGENT_SKILL_ENTITY.md))
- **Memory Cards** — Reusable patterns and knowledge

### Version Management

- Immutable version history
- Channel pinning — `latest`, `stable`, auto-promoted `evolved`, plus custom names (see [`docs/EVOLUTION_META.md`](docs/EVOLUTION_META.md))
- JSON-Patch diffs between versions (`?format=html` for a browser-friendly page)
- Rollback to previous versions
- Lineage walk: `GET /v1/chains/{id}/lineage`
- "Promotion candidates": `GET /v1/chains/{id}/versions/beating`

### Search

- BM25 full-text search (PostgreSQL `tsvector`)
- Vector search (`pgvector`, optional — `ENABLE_VECTOR_SEARCH=true`)
- Hybrid BM25 + vector with configurable weights
- Pluggable reranker (`RERANKER_KIND=`)
- CARE library knobs: `sort_by`, `sort_dir`, `favourites_only`, `tags`, `q`, `namespace`, plus AgentSkill-specific `requires_tool` / `excludes_tool`

### CARE library metadata

Every typed entity carries denormalised columns powering the CARE catalogue:

- `favourite` — toggled via `POST /v1/{type}/{id}/favourite`
- `run_count` + `last_run_at` — bumped via `POST /v1/{type}/{id}/run-recorded`
- `display_name` + `description` — mutated via `PATCH /v1/{type}/{id}` (no version bump)

### Authentication

Two auth schemes coexist (`api/app/auth.py`):

- **`X-API-Key: <key>`** — locally-issued keys against the `api_keys` table.
- **`Authorization: Bearer <jwt>`** — OIDC bearer tokens validated against the configured provider's JWKS. Enable with `OIDC_ENABLED=true` + `OIDC_ISSUER=...` (+ optional `OIDC_AUDIENCE`, `OIDC_JWKS_URI`, `OIDC_SUB_CLAIM`, `OIDC_SCOPES_CLAIM`).

When both headers are present, Bearer wins. Mode switch on `AUTH_REQUIRED`:

- **Opt-in mode** (dev/CI default, `AUTH_REQUIRED=false`) — missing both → anonymous context; invalid keys/tokens still `401`.
- **Strict mode** (production, `AUTH_REQUIRED=true`) — missing both also `401`.

Scopes: `read:any`, `write:any`, `delete:any`, `clear:all`, `admin:keys`, `evolve`. Writes auto-scope to `auth.owner` (and reads do the same unless the caller holds `read:any`). Issue local keys via `make create-key OWNER=alice [SCOPES=...]`; OIDC tokens project the configured scopes claim (space-separated string OR array) onto `AuthContext.scopes`.

### Real-time updates

- `GET /v1/events/stream` — SSE firehose of entity mutations.
- Event types: `created`, `updated`, `deleted`, `pinned`, `promoted`, `favourite_toggled`, `run_recorded`, `metadata_updated`.
- Filters: `?entity_type=` / `?entity_id=` / `?namespace=` / `?tags=` / `?event_type=`.
- Backpressure: `SSE_WARN_LAG_SECONDS` (10s default) → injected `lag_warning`; `SSE_DROP_LAG_SECONDS` (60s) → disconnect.

### Observability

- `GET /health` — connection-pool stats, Redis client counts, live entity counts.
- `GET /metrics` — Prometheus exposition: `gigaevo_memory_http_requests_total` (counter), `gigaevo_memory_http_request_duration_seconds` (histogram), `gigaevo_memory_entities` (gauge by entity_type).

### UI Features

- Browse entities by type (including AgentSkills)
- Edit entity content (JSON editor)
- Search across all entities
- Connection status monitoring

## 🏗️ Architecture

```text
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│  CARE TUI / MAGE    │   │  Web UI (Gradio)    │   │  Python SDK         │
│  (gigaevo-client)   │   │  host 7861 → 7860   │   │  gigaevo-client     │
└──────────┬──────────┘   └──────────┬──────────┘   └──────────┬──────────┘
           │                         │                         │
           └─────── X-API-Key ───────┴─────────────────────────┘
                                     │
                                     ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │            FastAPI Memory API  (host 8002 → container 8000)       │
   │                                                                  │
   │  Typed entity routers:                                           │
   │    /v1/steps   /v1/chains   /v1/agents                           │
   │    /v1/agent-skills   /v1/memory-cards                           │
   │                                                                  │
   │  Cross-cutting:                                                  │
   │    /v1/events/stream                (SSE firehose)               │
   │    /v1/search/unified, /v1/embeddings                            │
   │    /v1/versions/{...}/lineage, /diff?format=html|json            │
   │    /v1/chains/{id}/versions/beating (promotion candidates)       │
   │    /metrics                         (Prometheus exposition)      │
   │    /health                                                       │
   │                                                                  │
   │  Auth: X-API-Key + scopes (read:any, write:any, evolve, …)       │
   └────────────────────┬──────────────────────────┬──────────────────┘
                        │                          │
                        ▼                          ▼
        ┌─────────────────────────┐    ┌─────────────────────────┐
        │ PostgreSQL (pgvector)   │    │ Redis                   │
        │  entities, versions,    │    │  pub/sub "memory:events"│
        │  api_keys, search docs  │    │  → SSE firehose         │
        │  internal only          │    │  internal only          │
        └─────────────────────────┘    └─────────────────────────┘
```

## 📖 Documentation

- **API surface:** Swagger UI at `http://localhost:8002/docs`, OpenAPI spec [openapi.yaml](openapi.yaml).
- **Contract docs:**
  - [`docs/CARE_INTEGRATION.md`](docs/CARE_INTEGRATION.md) — umbrella contract for CARE: namespaces, auth, channels, library metadata, SSE event types.
  - [`docs/AGENT_SKILL_ENTITY.md`](docs/AGENT_SKILL_ENTITY.md) — `agent_skill` content schema, endpoints, search documents, ingestion helper.
  - [`docs/EVOLUTION_META.md`](docs/EVOLUTION_META.md) — `evolution_meta` schema, `evolved`-channel auto-promotion, lineage endpoint.
  - [`docs/CHAIN_CONTENT_CONVENTIONS.md`](docs/CHAIN_CONTENT_CONVENTIONS.md) — `CareChainMetadata` block inside `chain.content`.

## 🧪 Testing

```bash
make test
make test-integration
make client-test
```

## 🛠️ Operations

### Backups

`make backup` dumps the running Postgres instance to a gzip'd SQL file
in `./backups/`, optionally uploading it to S3.

```bash
# Local-only backup
make backup
# → ./backups/gigaevo-memory-20260516-164550Z.sql.gz

# With S3 upload
S3_BUCKET=gigaevo-prod-backups make backup
# → ./backups/gigaevo-memory-<ts>.sql.gz
# → s3://gigaevo-prod-backups/gigaevo-memory/backups/gigaevo-memory-<ts>.sql.gz

# Preview the commands without running them
make backup-dry-run
```

Environment variables (all optional, sensible defaults):

| Variable          | Default                          | Purpose                                  |
|-------------------|----------------------------------|------------------------------------------|
| `BACKUP_DIR`      | `./backups`                      | Local output directory                   |
| `POSTGRES_USER`   | `memory`                         | DB user passed to `pg_dump`              |
| `POSTGRES_DB`     | `memory`                         | DB name passed to `pg_dump`              |
| `COMPOSE_FILE`    | `deploy/docker-compose.yml`      | Path to docker-compose config            |
| `COMPOSE_PROJECT` | `gigaevo-memory`                 | Compose project name                     |
| `S3_BUCKET`       | *(unset)*                        | S3 bucket; upload is skipped when unset  |
| `S3_PREFIX`       | `gigaevo-memory/backups`         | Key prefix inside the S3 bucket          |

The dump filename embeds a UTC timestamp
(`gigaevo-memory-YYYYMMDD-HHMMSSZ.sql.gz`) so concurrent runs never
collide on filesystem nor S3 keys. Schedule it via cron / systemd
timer for automated rotation; couple it with a lifecycle policy on the
S3 bucket for long-term retention.

### Migration safety

`make migrate-check` runs the static migration-chain integrity tests
followed by the `alembic upgrade head → downgrade -1 → upgrade head`
round-trip — the same checks GitHub Actions runs on every push that
touches `api/app/db/migrations/`.

### API key issuance

`make create-key OWNER=alice [SCOPES=read:any,evolve]
[LABEL="alice's laptop"] [EXPIRES_DAYS=30]` issues a new key. The
plaintext is printed exactly once — copy it into a secrets manager
immediately. See `api/app/create_key.py` for the full CLI.

### Client configuration

The Python client reads its configuration from a single `GigaEvoConfig`
object. The canonical CARE entry point is
`MemoryClient.from_config(GigaEvoConfig.load())`, which composes settings
from three layers (lowest to highest precedence):

  1. Class defaults (`http://localhost:8000`, no key, 30s timeout).
  2. TOML at `~/.config/gigaevo/config.toml` (skipped silently when absent).
  3. Environment variables — `GIGAEVO_MEMORY_URL`, `GIGAEVO_PLATFORM_URL`,
     `GIGAEVO_API_KEY`.

```toml
# ~/.config/gigaevo/config.toml
memory_base_url = "https://memory.gigaevo.io"
api_key         = "sk-prod-abc123"
timeout         = 10.0
cache_ttl       = 600
```

Ship stable settings in the TOML; override the API key (or URL) via
environment variables in CI / shared shells without rewriting the file.

## 📄 License

MIT
