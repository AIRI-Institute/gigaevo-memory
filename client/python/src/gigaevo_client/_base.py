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
    "agent_skill": "agent-skills",
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
        api_key: str | None = None,
    ):
        """Initialize the base memory client.

        Args:
            base_url: Base URL of the Memory API server
            cache_policy: Caching strategy (TTL, FRESHNESS_CHECK, SSE_PUSH)
            cache_ttl: Time-to-live for TTL cache in seconds
            timeout: HTTP request timeout in seconds
            freshness_on_miss: Whether to perform freshness check on cache miss
            sse_prefetch: Whether to prefetch entities via SSE
            api_key: Optional API key sent on every request as the
                ``X-API-Key`` header. Required by strict-mode
                deployments; safe to omit in opt-in mode where the
                server returns an anonymous context.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        headers = {"X-API-Key": api_key} if api_key else None
        self._http = httpx.Client(
            base_url=self._base_url, timeout=timeout, headers=headers
        )
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
        *,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        favourites_only: bool | None = None,
        tags: list[str] | None = None,
        q: str | None = None,
        namespace: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> list[EntityResponse]:
        """List entities with pagination + CARE library knobs.

        Args:
            entity_type: Type of entity to list
            limit: Maximum number of results to return
            offset: Pagination offset
            channel: Version channel to retrieve (latest, stable, custom)
            sort_by: One of ``created_at``, ``last_run_at``, ``run_count``,
                ``display_name``. Routers default to ``last_run_at`` so the
                CARE library home view "feels right" out of the box.
            sort_dir: ``asc`` or ``desc``.
            favourites_only: Filter to ``favourite=TRUE`` rows.
            tags: Filter to entities whose ``tags`` JSONB contains ALL
                listed tokens. Sent as repeated ``tags`` query params.
            q: Case-insensitive substring across display_name / name /
                description.
            namespace: Restrict to a single CARE namespace.

        Returns:
            List of EntityResponse objects.
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        params: dict[str, Any] = {"limit": limit, "offset": offset, "channel": channel}
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_dir is not None:
            params["sort_dir"] = sort_dir
        if favourites_only is not None:
            params["favourites_only"] = favourites_only
        if tags:
            # httpx sends a list value as repeated `tags=…` query params,
            # which matches FastAPI's `tags: list[str] | None = Query(None)`.
            params["tags"] = list(tags)
        if q is not None:
            params["q"] = q
        if namespace is not None:
            params["namespace"] = namespace
        # Per-entity-type extras (e.g. `requires_tool` /
        # `excludes_tool` for agent_skills) — merge last so an
        # explicit kwarg above isn't accidentally clobbered.
        if extra_params:
            for k, v in extra_params.items():
                if v is None:
                    continue
                if isinstance(v, (list, tuple)) and not v:
                    continue
                params[k] = v

        resp = self._http.get(f"/v1/{plural}", params=params)
        data = self._handle_response(resp)
        return [EntityResponse.model_validate(e) for e in data]

    def _list_entities_paged(
        self,
        entity_type: str,
        cursor: str | None = None,
        limit: int = 50,
        channel: str = "latest",
        *,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        favourites_only: bool | None = None,
        tags: list[str] | None = None,
        q: str | None = None,
        namespace: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> tuple[list[EntityResponse], str | None, bool]:
        """Cursor-paginated list. Returns ``(items, next_cursor, has_more)``.

        Wraps the same `/v1/{plural}` endpoint as `_list_entities` but
        reads the `X-Next-Cursor` and `X-Has-More` response headers
        to expose stable keyset pagination at the typed-mixin level.

        ``cursor=None`` requests the first page. Subsequent calls pass
        the returned ``next_cursor`` to continue. ``has_more=False``
        signals end-of-stream.
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        params: dict[str, Any] = {"limit": limit, "channel": channel}
        if cursor is not None:
            params["cursor"] = cursor
        if sort_by is not None:
            params["sort_by"] = sort_by
        if sort_dir is not None:
            params["sort_dir"] = sort_dir
        if favourites_only is not None:
            params["favourites_only"] = favourites_only
        if tags:
            params["tags"] = list(tags)
        if q is not None:
            params["q"] = q
        if namespace is not None:
            params["namespace"] = namespace
        if extra_params:
            for k, v in extra_params.items():
                if v is None:
                    continue
                if isinstance(v, (list, tuple)) and not v:
                    continue
                params[k] = v

        resp = self._http.get(f"/v1/{plural}", params=params)
        data = self._handle_response(resp)
        items = [EntityResponse.model_validate(e) for e in data]
        next_cursor = resp.headers.get("X-Next-Cursor")
        has_more = resp.headers.get("X-Has-More", "false").lower() == "true"
        return items, next_cursor, has_more

    # ------------------------------------------------------------------ #
    #  CARE library mutation helpers (P0 §1.4)                            #
    # ------------------------------------------------------------------ #

    def _mark_favourite(
        self, entity_type: str, entity_id: str, value: bool = True
    ) -> EntityResponse:
        """POST /v1/{plural}/{id}/favourite — toggle the favourite flag."""
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.post(
            f"/v1/{plural}/{entity_id}/favourite",
            json={"favourite": bool(value)},
        )
        data = self._handle_response(resp)
        return EntityResponse.model_validate(data)

    def _record_run(
        self,
        entity_type: str,
        entity_id: str,
        run_id: str | None = None,
    ) -> EntityResponse:
        """POST /v1/{plural}/{id}/run-recorded — bump run_count + last_run_at."""
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        body: dict[str, Any] = {}
        if run_id is not None:
            body["run_id"] = run_id
        resp = self._http.post(
            f"/v1/{plural}/{entity_id}/run-recorded",
            json=body,
        )
        data = self._handle_response(resp)
        return EntityResponse.model_validate(data)

    def _update_metadata(
        self,
        entity_type: str,
        entity_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        favourite: bool | None = None,
    ) -> EntityResponse:
        """PATCH /v1/{plural}/{id} — partial update of CARE-mutable fields.

        Each kwarg is sent only when explicitly provided. Use ``tags=[]``
        to clear tags (distinct from omitting). Does NOT create a new
        version.
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        body: dict[str, Any] = {}
        if display_name is not None:
            body["display_name"] = display_name
        if description is not None:
            body["description"] = description
        if tags is not None:
            body["tags"] = list(tags)
        if favourite is not None:
            body["favourite"] = bool(favourite)
        resp = self._http.patch(f"/v1/{plural}/{entity_id}", json=body)
        data = self._handle_response(resp)
        return EntityResponse.model_validate(data)

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
