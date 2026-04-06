"""SSE event stream and webhook management."""

import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..events.publisher import get_redis

router = APIRouter()

CHANNEL = "memory:events"


@router.get("/events/stream")
async def event_stream(
    entity_type: str | None = None,
    entity_id: str | None = None,
    namespace: str | None = None,
):
    """Server-Sent Events stream for entity change notifications."""

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

                # Apply filters
                if entity_type and event.get("entity_type") != entity_type:
                    continue
                if entity_id and event.get("entity_id") != entity_id:
                    continue
                if namespace and event.get("namespace") != namespace:
                    continue

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
