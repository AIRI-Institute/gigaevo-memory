"""Client-side cache with configurable policies."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CachePolicy(StrEnum):
    """Cache invalidation strategy."""

    TTL = "ttl"
    FRESHNESS_CHECK = "freshness_check"
    SSE_PUSH = "sse_push"


class CacheEntry(BaseModel):
    """Single cache entry for an entity lookup."""

    model_config = {"arbitrary_types_allowed": True}

    entity_type: str
    entity_id: str
    channel: str
    version_id: str
    content_hash: str  # SHA-256
    parsed_object: Any = None
    raw_content: dict = Field(default_factory=dict)
    cached_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CacheStore:
    """In-memory cache keyed by (entity_type, entity_id, channel)."""

    def __init__(
        self,
        policy: CachePolicy = CachePolicy.TTL,
        ttl: int = 300,
    ):
        self._store: dict[tuple[str, str, str], CacheEntry] = {}
        self.policy = policy
        self.ttl = ttl

    def get(self, entity_type: str, entity_id: str, channel: str) -> CacheEntry | None:
        """Get a cache entry if it exists and is still valid."""
        key = (entity_type, entity_id, channel)
        entry = self._store.get(key)
        if entry is None:
            return None

        if self.policy == CachePolicy.TTL:
            elapsed = (datetime.now(timezone.utc) - entry.cached_at).total_seconds()
            if elapsed > self.ttl:
                del self._store[key]
                return None

        return entry

    def put(self, entry: CacheEntry) -> None:
        """Store or update a cache entry."""
        key = (entry.entity_type, entry.entity_id, entry.channel)
        self._store[key] = entry

    def invalidate(self, entity_id: str, channel: str | None = None) -> None:
        """Invalidate cache entries for an entity."""
        keys_to_delete = [
            k
            for k in self._store
            if k[1] == entity_id and (channel is None or k[2] == channel)
        ]
        for k in keys_to_delete:
            del self._store[k]

    def clear(self) -> None:
        """Clear the entire cache."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
