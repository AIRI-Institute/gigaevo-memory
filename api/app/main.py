"""GigaEvo Memory Module API — FastAPI entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .events.publisher import close_redis, get_redis
from .routers import agents, chains, embeddings, memory_cards, entities, events, health, steps, unified_search, versions


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

# Operational endpoints (no /v1 prefix)
app.include_router(health.router)

# Typed entity endpoints (recommended)
app.include_router(steps.router)
app.include_router(chains.router)
app.include_router(agents.router)
app.include_router(memory_cards.router)

# Generic entity endpoints (deprecated but kept for backward compatibility)
app.include_router(entities.router, prefix="/v1", tags=["entities (deprecated)"])

# Version management endpoints
app.include_router(versions.router, prefix="/v1", tags=["versions"])

# Search and events
app.include_router(unified_search.router, prefix="/v1", tags=["search"])
app.include_router(embeddings.router, prefix="/v1", tags=["search"])
app.include_router(events.router, prefix="/v1", tags=["events"])
