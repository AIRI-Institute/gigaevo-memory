"""SSE event stream and webhook management."""

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from ..config import settings
from ..events.publisher import get_redis

router = APIRouter()

CHANNEL = "memory:events"


def _compute_lag_action(
    event: dict,
    *,
    now: datetime | None = None,
    warn_threshold_s: float | None = None,
    drop_threshold_s: float | None = None,
) -> tuple[Literal["forward", "warn", "drop"], float | None]:
    """Inspect ``event["timestamp"]`` and decide what to do.

    Returns ``(action, lag_seconds)``. ``lag_seconds`` is ``None`` when
    the event carries no parseable timestamp (treated as ``"forward"``
    — no decision to make).

    Action semantics:
        * ``"forward"`` — within budget, emit the event normally.
        * ``"warn"``    — between the warn and drop thresholds; the
                          generator injects a `lag_warning` event
                          THEN still forwards the original event.
        * ``"drop"``    — above the drop threshold; the generator
                          closes the connection after emitting a final
                          `lag_warning` so the client knows why.

    Pure function (no I/O). Exposed so the test suite can exercise
    the decision logic without spinning up Redis / SSE.
    """
    raw = event.get("timestamp")
    if not raw:
        return ("forward", None)
    try:
        # Publisher emits ISO 8601 (`datetime.isoformat()`).
        published_at = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return ("forward", None)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    lag = (current - published_at).total_seconds()
    if lag < 0:
        # Clock skew — treat as no lag.
        return ("forward", lag)

    warn = warn_threshold_s if warn_threshold_s is not None else settings.sse_warn_lag_seconds
    drop = drop_threshold_s if drop_threshold_s is not None else settings.sse_drop_lag_seconds
    if lag >= drop:
        return ("drop", lag)
    if lag >= warn:
        return ("warn", lag)
    return ("forward", lag)


def _event_passes_filters(
    event: dict,
    *,
    entity_type: str | None,
    entity_id: str | None,
    namespace: str | None,
    tags: list[str] | None,
    event_type: str | None,
) -> bool:
    """Apply server-side filters to a single event payload.

    Tag semantics: an event passes the `tags` filter when its
    ``event["tags"]`` array intersects the requested tag set (OR
    semantics). Empty / missing event tags do not match a non-empty
    requested set.
    """
    if entity_type and event.get("entity_type") != entity_type:
        return False
    if entity_id and event.get("entity_id") != entity_id:
        return False
    if namespace and event.get("namespace") != namespace:
        return False
    if event_type and event.get("event_type") != event_type:
        return False
    if tags:
        evt_tags = event.get("tags") or []
        if not (set(evt_tags) & set(tags)):
            return False
    return True


@router.get("/events/stream")
async def event_stream(
    entity_type: str | None = None,
    entity_id: str | None = None,
    namespace: str | None = None,
    tags: list[str] | None = Query(default=None),
    event_type: str | None = None,
):
    """Server-Sent Events stream for entity change notifications.

    Filters (all optional, AND-combined; ``tags`` is OR within itself):
      * ``entity_type``  — exact match.
      * ``entity_id``    — exact match (single-entity subscription).
      * ``namespace``    — exact match (library-wide subscription).
      * ``tags``         — repeated query param (e.g. ``?tags=pdf&tags=q1``);
        an event matches when its tags intersect the requested set.
      * ``event_type``   — filter on event kind, e.g. ``run_recorded``
        for a stats widget that tracks runs only.
    """

    async def generate():
        redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                if not _event_passes_filters(
                    event,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    namespace=namespace,
                    tags=tags,
                    event_type=event_type,
                ):
                    continue

                action, lag = _compute_lag_action(event)
                if action in ("warn", "drop"):
                    yield {
                        "event": "lag_warning",
                        "data": json.dumps({
                            "lag_seconds": lag,
                            "warn_threshold_seconds": settings.sse_warn_lag_seconds,
                            "drop_threshold_seconds": settings.sse_drop_lag_seconds,
                            "action": action,
                            "for_event": {
                                "entity_id": event.get("entity_id"),
                                "entity_type": event.get("entity_type"),
                                "event_type": event.get("event_type"),
                                "timestamp": event.get("timestamp"),
                            },
                        }),
                    }
                if action == "drop":
                    # Close the connection by exiting the generator;
                    # the `finally` block below cleans the pubsub up.
                    return

                yield {
                    "event": "entity_changed",
                    "data": json.dumps(event),
                }
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.close()

    return EventSourceResponse(generate())


@router.post("/webhooks", status_code=501)
async def create_webhook():
    """Register a webhook (not yet implemented)."""
    raise HTTPException(status_code=501, detail="Webhooks not yet implemented")


@router.delete("/webhooks/{webhook_id}", status_code=501)
async def delete_webhook(webhook_id: str):
    """Delete a webhook (not yet implemented)."""
    raise HTTPException(status_code=501, detail="Webhooks not yet implemented")
