"""GigaEvo Memory Module API — FastAPI entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .events.publisher import close_redis, get_redis
from .metrics import metrics_middleware
from .metrics import router as metrics_router
from .routers import (
    agent_skills,
    agents,
    bulk,
    chains,
    dedup,
    embeddings,
    entities,
    events,
    health,
    memory_cards,
    steps,
    unified_search,
    versions,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown lifecycle."""
    # Startup: warm up Redis connection
    await get_redis()
    yield
    # Shutdown: close Redis
    await close_redis()


app = FastAPI(
    title="GigaEvo Memory Module",
    description="Persistent memory for CARL artifacts: steps, chains, agents, memory cards",
    version="0.1.0",
    lifespan=lifespan,
)

# Metrics: record counter + histogram for every request EXCEPT /metrics
# itself. Registered before any router so it wraps the full handler
# stack; the middleware skips its own scrape path internally.
app.middleware("http")(metrics_middleware)

# Operational endpoints (no /v1 prefix)
app.include_router(health.router)
app.include_router(metrics_router)

# Semantic deduplication. MUST be registered before the typed entity
# routers — its path is `/v1/{entity_type}/duplicates`, and the typed
# routers declare `/v1/{type}/{entity_id}` which would otherwise try
# to parse the literal `"duplicates"` as a UUID and 422 the request.
app.include_router(dedup.router, prefix="/v1")

# Typed entity endpoints (recommended)
app.include_router(steps.router)
app.include_router(chains.router)
app.include_router(agents.router)
app.include_router(agent_skills.router)
app.include_router(memory_cards.router)

# Bulk import (CARE's `care import` consumer)
app.include_router(bulk.router, prefix="/v1", tags=["bulk"])

# Generic entity endpoints (deprecated but kept for backward compatibility)
app.include_router(entities.router, prefix="/v1", tags=["entities (deprecated)"])

# Version management endpoints
app.include_router(versions.router, prefix="/v1", tags=["versions"])

# Search and events
app.include_router(unified_search.router, prefix="/v1", tags=["search"])
app.include_router(embeddings.router, prefix="/v1", tags=["search"])
app.include_router(events.router, prefix="/v1", tags=["events"])
