"""Shared infrastructure base class for MemoryClient.

Provides common HTTP, caching, and entity operations used across all entity mixins.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from .cache import CacheEntry, CachePolicy, CacheStore
from ._compat import to_jsonable
from .exceptions import ConflictError, NotFoundError, ValidationError
from .models import EntityRef, EntityResponse


_TYPE_PLURAL = {
    "chain": "chains",
    "step": "steps",
    "agent": "agents",
    "memory_card": "memory-cards",
}


class BaseMemoryClient:
    """Base class providing shared HTTP and caching infrastructure.

    This class contains the core functionality used by all entity-specific mixins:
    - HTTP client configuration
    - Caching logic
    - Generic entity CRUD operations
    - Response handling
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        cache_policy: CachePolicy = CachePolicy.TTL,
        cache_ttl: int = 300,
        timeout: float = 30.0,
        freshness_on_miss: bool = False,
        sse_prefetch: bool = False,
    ):
        """Initialize the base memory client.

        Args:
            base_url: Base URL of the Memory API server
            cache_policy: Caching strategy (TTL, FRESHNESS_CHECK, SSE_PUSH)
            cache_ttl: Time-to-live for TTL cache in seconds
            timeout: HTTP request timeout in seconds
            freshness_on_miss: Whether to perform freshness check on cache miss
            sse_prefetch: Whether to prefetch entities via SSE
        """
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self._base_url, timeout=timeout)
        self.cache = CacheStore(policy=cache_policy, ttl=cache_ttl)
        self._freshness_on_miss = freshness_on_miss
        self._sse_prefetch = sse_prefetch

    def _get_entity(
        self,
        entity_type: str,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Fetch an entity with caching logic.

        Args:
            entity_type: Type of entity (chain, step, agent, memory_card)
            entity_id: Unique identifier for the entity
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            Dictionary with 'content', 'version_id', and 'entity_id' keys
        """
        # Check cache
        if not force_refresh:
            entry = self.cache.get(entity_type, entity_id, channel)
            if entry is not None:
                if self.cache.policy == CachePolicy.FRESHNESS_CHECK:
                    # Conditional GET
                    headers = {"If-None-Match": entry.content_hash}
                    plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
                    resp = self._http.get(
                        f"/v1/{plural}/{entity_id}",
                        params={"channel": channel},
                        headers=headers,
                    )
                    if resp.status_code == 304:
                        return {
                            "content": entry.raw_content,
                            "version_id": entry.version_id,
                            "entity_id": entity_id,
                        }
                    data = self._handle_response(resp)
                    self._cache_response(entity_type, entity_id, channel, data)
                    return data
                else:
                    return {
                        "content": entry.raw_content,
                        "version_id": entry.version_id,
                        "entity_id": entity_id,
                    }

        # Cache miss: fetch from server
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.get(f"/v1/{plural}/{entity_id}", params={"channel": channel})
        data = self._handle_response(resp)
        self._cache_response(entity_type, entity_id, channel, data)
        return data

    def _save_entity(
        self,
        entity_type: str,
        content: dict,
        name: str,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        namespace: str | None = None,
        entity_id: str | None = None,
        channel: str = "latest",
        evolution_meta: dict | None = None,
    ) -> EntityRef:
        """Create or update an entity.

        Args:
            entity_type: Type of entity (chain, step, agent, memory_card)
            content: Entity content as a dictionary
            name: Human-readable name for the entity
            tags: Optional list of tags for categorization
            when_to_use: Optional description of when to use this entity
            author: Optional author attribution
            namespace: Optional logical memory namespace
            entity_id: If provided, update existing entity; otherwise create new
            channel: Version channel to update (latest, stable, custom)
            evolution_meta: Optional evolutionary metadata for chains/steps

        Returns:
            EntityRef with entity_id, version_id, and channel
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        body: dict[str, Any] = {
            "meta": {
                "name": name,
                "tags": tags or [],
                "when_to_use": when_to_use,
                "namespace": namespace,
                "author": author,
            },
            "channel": channel,
            "content": content,
        }
        if evolution_meta:
            body["evolution_meta"] = evolution_meta

        body = to_jsonable(body)

        if entity_id:
            resp = self._http.put(f"/v1/{plural}/{entity_id}", json=body)
        else:
            resp = self._http.post(f"/v1/{plural}", json=body)

        data = self._handle_response(resp)
        return EntityRef(
            entity_id=data["entity_id"],
            entity_type=entity_type,
            version_id=data.get("version_id"),
            channel=channel,
        )

    def _list_entities(
        self,
        entity_type: str,
        limit: int = 50,
        offset: int = 0,
        channel: str = "latest",
    ) -> list[EntityResponse]:
        """List entities with pagination.

        Args:
            entity_type: Type of entity to list
            limit: Maximum number of results to return
            offset: Pagination offset
            channel: Version channel to retrieve (latest, stable, custom)

        Returns:
            List of EntityResponse objects
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.get(f"/v1/{plural}", params={"limit": limit, "offset": offset, "channel": channel})
        data = self._handle_response(resp)
        return [EntityResponse.model_validate(e) for e in data]

    def _delete_entity(self, entity_type: str, entity_id: str) -> bool:
        """Soft-delete an entity.

        Args:
            entity_type: Type of entity to delete
            entity_id: Unique identifier for the entity

        Returns:
            True if deletion was successful
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.delete(f"/v1/{plural}/{entity_id}")
        # Handle 204 No Content or 200 OK
        if resp.status_code == 204:
            return True
        self._handle_response(resp)
        return True

    def _cache_response(
        self,
        entity_type: str,
        entity_id: str,
        channel: str,
        data: dict,
    ) -> None:
        """Cache a successful API response.

        Args:
            entity_type: Type of entity
            entity_id: Unique identifier for the entity
            channel: Version channel
            data: Response data to cache
        """
        content = data.get("content", {})
        self.cache.put(
            CacheEntry(
                entity_type=entity_type,
                entity_id=entity_id,
                channel=channel,
                version_id=data.get("version_id", ""),
                content_hash=self._content_hash(content),
                raw_content=content,
            )
        )

    @staticmethod
    def _content_hash(content: dict) -> str:
        """Compute SHA-256 hash of content for ETag/freshness checks.

        Args:
            content: Content dictionary to hash

        Returns:
            Hexadecimal SHA-256 hash string
        """
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _handle_response(self, resp: httpx.Response) -> dict:
        """Handle HTTP response, raising appropriate exceptions on error.

        Args:
            resp: HTTP response object

        Returns:
            Response JSON as a dictionary

        Raises:
            NotFoundError: If entity not found (404)
            ConflictError: On optimistic concurrency conflict (409/412)
            ValidationError: On request validation failure (422)
            httpx.HTTPStatusError: For other HTTP errors
        """
        if resp.status_code == 404:
            raise NotFoundError(f"Not found: {resp.url}")
        if resp.status_code in (409, 412):
            raise ConflictError(f"Conflict: {resp.text}")
        if resp.status_code == 422:
            raise ValidationError(f"Validation error: {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        """Close the underlying HTTP client.

        Should be called when done using the client, or use as a context manager.
        """
        self._http.close()

    def __enter__(self) -> BaseMemoryClient:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit - ensures HTTP client is closed."""
        self.close()
