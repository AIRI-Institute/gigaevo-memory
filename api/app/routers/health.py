"""Health check and metrics endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db
from ..events.publisher import get_redis

router = APIRouter()


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Check health of API and all dependencies."""
    status = {"status": "ok", "postgres": "unknown", "redis": "unknown"}

    # Check PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as e:
        status["postgres"] = f"error: {e}"
        status["status"] = "degraded"

    # Check Redis
    try:
        redis = await get_redis()
        await redis.ping()
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {e}"
        status["status"] = "degraded"

    return status


@router.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics stub."""
    return {
        "uptime_seconds": 0,
        "requests_total": 0,
        "note": "Full Prometheus metrics to be implemented",
    }
