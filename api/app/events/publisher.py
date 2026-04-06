"""Redis pub/sub event publisher for entity changes."""

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis

from ..config import settings

CHANNEL = "memory:events"

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


async def publish_entity_event(
    event_type: str,
    entity_id: str,
    entity_type: str,
    version_id: str | None = None,
    channel: str | None = None,
) -> None:
    """Publish an entity change event to Redis."""
    r = await get_redis()
    event = {
        "event_type": event_type,
        "entity_id": str(entity_id),
        "entity_type": entity_type,
        "version_id": str(version_id) if version_id else None,
        "channel": channel,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await r.publish(CHANNEL, json.dumps(event))
