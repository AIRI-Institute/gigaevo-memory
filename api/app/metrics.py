"""Prometheus metrics — request counts, latency histograms, entity gauges.

Three series exposed at ``GET /metrics``:

* ``gigaevo_memory_http_requests_total`` — counter labelled by
  ``method`` / ``path_template`` / ``status``. ``path_template`` is the
  FastAPI route pattern (e.g. ``/v1/chains/{chain_id}``), **not** the
  raw path — keeps label cardinality bounded.
* ``gigaevo_memory_http_request_duration_seconds`` — histogram labelled
  by ``method`` / ``path_template``. Buckets cover the typical p50–p99
  range for a memory-backed API (5ms → 10s).
* ``gigaevo_memory_entities`` — gauge labelled by ``entity_type``,
  reporting the count of **non-deleted** rows in ``entities`` per type.
  Refreshed lazily on every ``/metrics`` scrape (Prometheus's default
  15s cadence is well within Postgres budget).

Cardinality discipline: every metric labels stay bounded — methods are
HTTP verbs (≤ 9), path templates are bounded by the router (~40), status
codes are 3-digit ints (~30 in practice), entity types are the 5 in
``VALID_ENTITY_TYPES``. Max series ≈ 9 × 40 × 30 = 10800, well within
Prometheus's comfort zone.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from .db.models import Entity
from .db.session import async_session

# ---------------------------------------------------------------------------
# Registry + metric series
# ---------------------------------------------------------------------------

#: Dedicated registry — keeps the GigaEvo series out of the default
#: process registry so we don't accidentally export unrelated metrics.
REGISTRY = CollectorRegistry()

# Histogram buckets in seconds. Tuned for typical memory-API latencies:
# fast cache hits at ~1–5ms, normal CRUD at 10–100ms, vector search at
# 100ms–1s, occasional slow paths under 10s. ``+Inf`` is implicit.
_DURATION_BUCKETS = (
    0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500,
    1.000, 2.500, 5.000, 10.000,
)

http_requests_total: Counter = Counter(
    "gigaevo_memory_http_requests_total",
    "Total HTTP requests handled, labelled by method, route template, and status.",
    labelnames=("method", "path_template", "status"),
    registry=REGISTRY,
)

http_request_duration_seconds: Histogram = Histogram(
    "gigaevo_memory_http_request_duration_seconds",
    "HTTP request handler duration in seconds, labelled by method and route template.",
    labelnames=("method", "path_template"),
    buckets=_DURATION_BUCKETS,
    registry=REGISTRY,
)

entities_gauge: Gauge = Gauge(
    "gigaevo_memory_entities",
    "Count of non-deleted entities per entity_type.",
    labelnames=("entity_type",),
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Path-template extraction
# ---------------------------------------------------------------------------


def _resolve_path_template(request: Request) -> str:
    """Return the FastAPI route template for a request, or ``"unmatched"``.

    Using the raw URL would balloon cardinality (every UUID would mint
    a new label set). Starlette resolves the matched route into
    ``request.scope["route"]``; we read ``.path`` off it when present.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    # Fallback: 404s and other unmatched paths share one label so they
    # don't blow up cardinality.
    return "unmatched"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


async def metrics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """ASGI middleware that records the counter + histogram per request.

    Skips its own scrape path so ``/metrics`` doesn't contribute to its
    own counters (avoids confusing self-referential spikes when
    Prometheus scrapes every 15s).
    """
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    status = 500  # Pessimistic default — overwritten on the happy path.
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    except Exception:
        # The counter still fires (with status=500) so a flood of 5xx is
        # visible even when the response object never makes it back.
        raise
    finally:
        duration = time.perf_counter() - start
        template = _resolve_path_template(request)
        http_requests_total.labels(
            method=request.method,
            path_template=template,
            status=str(status),
        ).inc()
        http_request_duration_seconds.labels(
            method=request.method,
            path_template=template,
        ).observe(duration)


# ---------------------------------------------------------------------------
# Entity-count refresh
# ---------------------------------------------------------------------------


async def refresh_entity_counts() -> None:
    """Repopulate ``entities_gauge`` from the live database.

    Best-effort: a transient DB failure logs and leaves the previous
    values in place rather than failing the scrape. Called at scrape
    time so values are always within one scrape interval of truth.
    """
    try:
        async with async_session() as session:
            stmt = (
                select(Entity.entity_type, func.count())
                .where(Entity.deleted_at.is_(None))
                .group_by(Entity.entity_type)
            )
            result = await session.execute(stmt)
            rows = result.all()
    except SQLAlchemyError:
        # The gauge keeps its last good values; Prometheus's `absent_over_time`
        # alert can pick this up if the failure is persistent.
        return

    # Reset before repopulating so a type that was deleted-down-to-zero
    # disappears from the export instead of carrying stale data.
    entities_gauge.clear()
    for entity_type, count in rows:
        entities_gauge.labels(entity_type=entity_type).set(count)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    """Prometheus scrape endpoint.

    Returns the standard text exposition format. Excluded from
    OpenAPI — Prometheus doesn't read OpenAPI, and keeping
    ``/metrics`` out of the public schema makes ``GET /docs`` less
    cluttered.
    """
    await refresh_entity_counts()
    payload = generate_latest(REGISTRY)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
