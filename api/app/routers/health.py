"""Health check and metrics endpoints."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import engine, get_db
from ..events.publisher import get_redis

router = APIRouter()


async def _collect_db_pool_stats() -> dict[str, Any]:
    """Read SQLAlchemy connection-pool counters off the async engine.

    Returns a dict suitable for direct merge into the /health payload.
    On error each field is None so a metric outage doesn't blow up the
    overall status check.
    """
    try:
        pool = engine.sync_engine.pool
        return {
            "db_pool_size": pool.size(),
            "db_pool_checkedin": pool.checkedin(),
            "db_pool_checkedout": pool.checkedout(),
            "db_pool_overflow": pool.overflow(),
        }
    except Exception:
        return {
            "db_pool_size": None,
            "db_pool_checkedin": None,
            "db_pool_checkedout": None,
            "db_pool_overflow": None,
        }


async def _collect_entity_counts(db: AsyncSession) -> dict[str, int] | None:
    """Aggregate live-entity counts by ``entity_type``.

    Single SELECT (filtered to ``deleted_at IS NULL``). Returns None
    on error — CARE's status bar renders the missing metric as ``—``.
    """
    try:
        result = await db.execute(
            text(
                "SELECT entity_type, COUNT(*) "
                "FROM entities WHERE deleted_at IS NULL "
                "GROUP BY entity_type"
            )
        )
        return {row[0]: int(row[1]) for row in result.all()}
    except Exception:
        return None


async def _collect_redis_metrics() -> dict[str, Any]:
    """Pull a thin slice of ``redis.info()`` — just the fields CARE
    surfaces in its status bar. Each field is None on error."""
    try:
        redis = await get_redis()
        info = await redis.info("clients")
        return {
            "redis_connected_clients": int(info.get("connected_clients", 0)),
            "redis_blocked_clients": int(info.get("blocked_clients", 0)),
        }
    except Exception:
        return {
            "redis_connected_clients": None,
            "redis_blocked_clients": None,
        }


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Check health of API and all dependencies.

    Beyond the binary ``ok | degraded`` status, the payload now
    includes connection-pool stats, redis client counts, and live
    entity counts — what CARE's TUI status bar consumes for live
    operational visibility.
    """
    status: dict[str, Any] = {"status": "ok", "postgres": "unknown", "redis": "unknown"}

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

    # Operational metrics — independent of the binary status. A metric
    # outage degrades the metric to None but doesn't flip the overall
    # status. The status flip is reserved for the dependency pings
    # above.
    status.update(await _collect_db_pool_stats())
    status.update(await _collect_redis_metrics())
    status["entity_counts"] = (
        await _collect_entity_counts(db) if status["postgres"] == "ok" else None
    )

    return status
