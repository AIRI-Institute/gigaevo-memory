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
- **Memory Cards** — Reusable patterns and knowledge

### Version Management

- Immutable version history
- Channel pinning (latest, stable, custom)
- Diffs between versions
- Rollback to previous versions

### Search

- Full-text search
- Filtering by entity type
- Filtering by tags
- Faceted search

### UI Features

- Browse entities by type
- Edit entity content (JSON editor)
- Search across all entities
- Connection status monitoring

## 🏗️ Architecture

```text
┌─────────────────────────────┐
│  Web UI                     │  Gradio
│  host 7861 -> container 7860│
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  FastAPI API                │  REST API
│  host 8002 -> container 8000│
└──────────────┬──────────────┘
               │
               ├─────────┐
               ▼         ▼
┌──────────────┐ ┌──────────────┐
│ PostgreSQL   │ │ Redis        │
│ internal only│ │ internal only│
└──────────────┘ └──────────────┘
```

## 📖 API Documentation

- **Swagger UI:** `http://localhost:8002/docs`
- **OpenAPI Specification:** [openapi.yaml](openapi.yaml)

## 🧪 Testing

```bash
make test
make test-integration
make client-test
```

## 📄 License

MIT
