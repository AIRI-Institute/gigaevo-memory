"""Memory card entity operations.

Provides methods for working with memory card specifications.
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, cast

from ._base import BaseMemoryClient
from .models import EntityRef, EntityResponse, MemoryCardSpec


class _MemoryCardSearchClient(Protocol):
    """Typing protocol for clients that also expose the search mixin."""

    def search(
        self,
        query: str,
        search_type: Any = ...,
        top_k: int = ...,
        entity_type: str = ...,
        embedding_provider: Any = ...,
        hybrid_weights: tuple[float, float] = ...,
        namespace: str | None = ...,
    ) -> list[MemoryCardSpec]: ...


class MemoryCardsMixin(BaseMemoryClient):
    """Mixin providing memory card operations.

    This mixin provides methods for:
    - Retrieving memory cards as MemoryCardSpec or raw dicts
    - Saving memory cards with automatic type conversion
    - Listing and deleting memory cards
    - Specialized search returning typed MemoryCardSpec objects
    """

    # =========================================================================
    # Memory card operations - Typed methods
    # =========================================================================

    def get_memory_card(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> MemoryCardSpec:
        """Get a memory card specification.

        Args:
            entity_id: Unique identifier for the memory card
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            MemoryCardSpec object
        """
        data = self._get_entity("memory_card", entity_id, channel, cache_ttl, force_refresh)
        return MemoryCardSpec.model_validate(data["content"])

    # =========================================================================
    # Memory card operations - Raw dict methods
    # =========================================================================

    def get_memory_card_dict(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Get memory card content as a raw dict.

        Args:
            entity_id: Unique identifier for the memory card
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            Raw memory card content as a dictionary
        """
        data = self._get_entity("memory_card", entity_id, channel, cache_ttl, force_refresh)
        return data["content"]

    # =========================================================================
    # Save methods
    # =========================================================================

    def save_memory_card(
        self,
        memory_card: MemoryCardSpec | dict,
        name: str,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        entity_id: str | None = None,
        channel: str = "latest",
        namespace: str | None = None,
    ) -> EntityRef:
        """Save a memory card specification.

        Args:
            memory_card: MemoryCardSpec object or dict with memory card content
            name: Human-readable name for the memory card
            tags: Optional list of tags for categorization
            when_to_use: Optional description of when to use this memory card
            namespace: Optional logical memory namespace
            author: Optional author attribution
            entity_id: If provided, update existing memory card; otherwise create new
            channel: Version channel to update (latest, stable, custom)

        Returns:
            EntityRef with entity_id, version_id, and channel
        """
        content = memory_card.model_dump(mode="json") if isinstance(memory_card, MemoryCardSpec) else memory_card
        return self._save_entity(
            "memory_card",
            content,
            name,
            tags,
            when_to_use,
            author,
            namespace=namespace,
            entity_id=entity_id,
            channel=channel,
        )

    # =========================================================================
    # List methods
    # =========================================================================

    def list_memory_cards(self, limit: int = 50, offset: int = 0, channel: str = "latest") -> list[EntityResponse]:
        """List all memory cards with pagination.

        Args:
            limit: Maximum number of results to return
            offset: Pagination offset
            channel: Version channel to retrieve (latest, stable, custom)

        Returns:
            List of EntityResponse objects for memory cards
        """
        return self._list_entities("memory_card", limit=limit, offset=offset, channel=channel)

    # =========================================================================
    # Delete methods
    # =========================================================================

    def delete_memory_card(self, entity_id: str) -> bool:
        """Soft-delete a memory card.

        Args:
            entity_id: Unique identifier for the memory card

        Returns:
            True if deletion was successful
        """
        return self._delete_entity("memory_card", entity_id)

    # =========================================================================
    # Search methods
    # =========================================================================

    def search_memory_cards(self, q: str, k: int = 5) -> list[MemoryCardSpec]:
        """Search memory cards by when_to_use context and return full MemoryCardSpec objects.

        This is a convenience wrapper around the search mixin specialized for
        memory-card results.

        Args:
            q: Search query string
            k: Maximum number of results to return

        Returns:
            List of MemoryCardSpec objects matching the search query
        """
        search_client = cast(_MemoryCardSearchClient, self)
        return search_client.search(query=q, entity_type="memory_card", top_k=k)

    def batch_download(
        self,
        batch_size: int = 50,
        size_limit: int = -1,
        channel: str = "latest",
    ) -> Iterator[list[MemoryCardSpec]]:
        """Download all memory cards in batches using a generator iterator.

        Automatically handles pagination to yield batches of memory cards from the server.
        Efficient for processing large datasets - yields batches as they are fetched
        rather than loading everything into memory.

        Args:
            batch_size: Number of memory cards to fetch per request (default: 50)
            size_limit: Maximum number of memory cards to yield; -1 for unlimited (default: -1)
            channel: Version channel to retrieve (latest, stable, custom)

        Yields:
            Lists of MemoryCardSpec objects, one batch per yield

        Example:
            >>> for batch in client.batch_download(batch_size=100):
            ...     for card in batch:
            ...         print(f"{card.id}: {card.description}")
        """
        offset = 0
        total_yielded = 0

        while True:
            # Check size limit before fetching next batch
            if size_limit >= 0 and total_yielded >= size_limit:
                break

            # Fetch a batch of memory cards
            entities = self._list_entities(
                "memory_card",
                limit=batch_size,
                offset=offset,
                channel=channel,
            )

            # No more entities to fetch
            if not entities:
                break

            # Convert entities to MemoryCardSpec objects
            batch = [MemoryCardSpec.model_validate(entity.content) for entity in entities]

            # Apply size limit if needed
            if size_limit >= 0:
                remaining = size_limit - total_yielded
                if remaining < len(batch):
                    batch = batch[:remaining]

            yield batch
            total_yielded += len(batch)

            # Check if we've reached the size limit
            if size_limit >= 0 and total_yielded >= size_limit:
                break

            # If we got fewer than batch_size, we've reached the end
            if len(entities) < batch_size:
                break

            offset += batch_size
