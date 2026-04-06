"""MemoryClient — main interface for the GigaEvo Memory Module."""

from __future__ import annotations

from typing import Any

from ._base import _TYPE_PLURAL, BaseMemoryClient
from .agents import AgentsMixin
from .cache import CachePolicy
from .chains import ChainsMixin
from .embeddings import EmbeddingProvider, get_default_provider
from .memory_cards import MemoryCardsMixin
from .models import (
    DiffResponse,
    EntityRef,
    FacetsResponse,
    MemoryCardSpec,
    SearchHitData,
    VersionDetail,
    VersionInfo,
)
from .search_types import SearchType


# =============================================================================
# Search Mixin
# =============================================================================


class SearchMixin(BaseMemoryClient):
    """Mixin providing search operations.

    This mixin provides methods for:
    - Unified search (BM25, vector, or hybrid) with automatic embedding
    - Batch search for multiple queries
    - Facet counts for UI filters
    """

    def __init__(self, *args, embedding_provider: EmbeddingProvider | None = None, **kwargs):
        """Initialize with optional embedding provider.

        Args:
            *args: Passed to BaseMemoryClient
            embedding_provider: Provider for generating embeddings. Uses default if None.
            **kwargs: Passed to BaseMemoryClient
        """
        super().__init__(*args, **kwargs)
        self._embedding_provider = embedding_provider

    def _get_embedding_provider(self) -> EmbeddingProvider:
        """Get the embedding provider (cached or default)."""
        if self._embedding_provider is None:
            self._embedding_provider = get_default_provider()
        return self._embedding_provider

    def search(
        self,
        query: str,
        search_type: SearchType = SearchType.BM25,
        top_k: int = 10,
        entity_type: str = "memory_card",
        channel: str = "latest",
        embedding_provider: EmbeddingProvider | None = None,
        document_kind: str | None = None,
        hybrid_weights: tuple[float, float] = (0.5, 0.5),
        namespace: str | None = None,
    ) -> list[MemoryCardSpec]:
        """Search entities using BM25, vector, or hybrid similarity.

        This is the primary search method that supports three search types:
        - BM25: Full-text search using PostgreSQL tsvector
        - Vector: Semantic search using pgvector similarity
        - Hybrid: Combined BM25 + Vector scores with configurable weights

        For vector and hybrid search, embeddings are automatically generated
        using the configured embedding provider.

        Args:
            query: Search query text
            search_type: Type of search (bm25, vector, or hybrid)
            top_k: Number of top results to return
            entity_type: Type of entity to search (memory_card by default)
            embedding_provider: Optional custom embedding provider for this search
            document_kind: Optional memory-card search document kind
            hybrid_weights: Weights for hybrid search (bm25_weight, vector_weight)

        Returns:
            List of MemoryCardSpec objects ranked by relevance

        Example:
            >>> # BM25 search
            >>> results = client.search("financial analysis", search_type=SearchType.BM25)
            >>>
            >>> # Vector search (auto-embeds query)
            >>> results = client.search("semantic similarity", search_type=SearchType.VECTOR)
            >>>
            >>> # Hybrid search with custom weights
            >>> results = client.search("analysis", search_type=SearchType.HYBRID, hybrid_weights=(0.3, 0.7))
            >>>
            >>> # Custom embedding provider
            >>> from gigaevo_memory.embeddings import OpenAIProvider
            >>> provider = OpenAIProvider(api_key="sk-...")
            >>> results = client.search("query", search_type=SearchType.VECTOR, embedding_provider=provider)
        """
        hits = self.search_hits(
            query=query,
            search_type=search_type,
            top_k=top_k,
            entity_type=entity_type,
            namespace=namespace,
            channel=channel,
            embedding_provider=embedding_provider,
            document_kind=document_kind,
            hybrid_weights=hybrid_weights,
        )
        return [
            MemoryCardSpec.model_validate(hit.content or {})
            for hit in hits
        ]

    def search_hits(
        self,
        query: str,
        search_type: SearchType = SearchType.BM25,
        top_k: int = 10,
        entity_type: str = "memory_card",
        channel: str = "latest",
        embedding_provider: EmbeddingProvider | None = None,
        document_kind: str | None = None,
        hybrid_weights: tuple[float, float] = (0.5, 0.5),
        namespace: str | None = None,
    ) -> list[SearchHitData]:
        """Search entities and return raw hit metadata."""
        if search_type == SearchType.BM25:
            return self._bm25_search_hits_internal(
                query=query,
                top_k=top_k,
                entity_type=entity_type,
                namespace=namespace,
                channel=channel,
                document_kind=document_kind,
            )
        if search_type in (SearchType.VECTOR, SearchType.HYBRID):
            provider = embedding_provider or self._get_embedding_provider()
            query_vector = provider.embed_query(query)
            return self._vector_or_hybrid_search_hits_internal(
                query=query,
                query_vector=query_vector,
                top_k=top_k,
                entity_type=entity_type,
                namespace=namespace,
                channel=channel,
                document_kind=document_kind,
                search_type=search_type,
                hybrid_weights=hybrid_weights,
            )
        raise ValueError(f"Unknown search_type: {search_type}")

    def batch_search(
        self,
        queries: list[str],
        search_type: SearchType = SearchType.BM25,
        top_k: int = 10,
        entity_type: str = "memory_card",
        channel: str = "latest",
        embedding_provider: EmbeddingProvider | None = None,
        document_kind: str | None = None,
        hybrid_weights: tuple[float, float] = (0.5, 0.5),
        namespace: str | None = None,
    ) -> list[list[MemoryCardSpec]]:
        """Batch search for multiple queries.

        Efficiently processes multiple queries in a single call. For vector and hybrid search,
        embeddings are generated in batch for better performance.

        Args:
            queries: List of search query texts
            search_type: Type of search (bm25, vector, or hybrid)
            top_k: Number of top results per query
            entity_type: Type of entity to search
            embedding_provider: Optional custom embedding provider
            document_kind: Optional memory-card search document kind
            hybrid_weights: Weights for hybrid search (bm25_weight, vector_weight)

        Returns:
            List of result lists, one per query

        Example:
            >>> queries = ["financial analysis", "code review", "documentation"]
            >>> results = client.batch_search(queries, search_type=SearchType.HYBRID)
            >>> for query, hits in zip(queries, results):
            ...     print(f"{query}: {len(hits)} results")
        """
        hit_batches = self.batch_search_hits(
            queries=queries,
            search_type=search_type,
            top_k=top_k,
            entity_type=entity_type,
            namespace=namespace,
            channel=channel,
            embedding_provider=embedding_provider,
            document_kind=document_kind,
            hybrid_weights=hybrid_weights,
        )
        return [
            [MemoryCardSpec.model_validate(hit.content or {}) for hit in hits]
            for hits in hit_batches
        ]

    def batch_search_hits(
        self,
        queries: list[str],
        search_type: SearchType = SearchType.BM25,
        top_k: int = 10,
        entity_type: str = "memory_card",
        channel: str = "latest",
        embedding_provider: EmbeddingProvider | None = None,
        document_kind: str | None = None,
        hybrid_weights: tuple[float, float] = (0.5, 0.5),
        namespace: str | None = None,
    ) -> list[list[SearchHitData]]:
        """Batch search entities and return raw hit metadata."""
        if not queries:
            return []

        payload: dict[str, Any] = {
            "search_type": search_type.value,
            "queries": queries,
            "top_k": top_k,
            "entity_type": entity_type,
            "channel": channel,
        }
        if namespace:
            payload["namespace"] = namespace
        if document_kind:
            payload["document_kind"] = document_kind
        if search_type in (SearchType.VECTOR, SearchType.HYBRID):
            provider = embedding_provider or self._get_embedding_provider()
            payload["query_vectors"] = provider.embed(queries)
        if search_type == SearchType.HYBRID:
            payload["hybrid_weights"] = list(hybrid_weights)

        resp = self._http.post("/v1/search/batch", json=payload)
        data = self._handle_response(resp)
        return [
            [SearchHitData.model_validate(hit) for hit in hits]
            for hits in data["results"]
        ]

    def _vector_search_internal(
        self,
        query_vector: list[float],
        top_k: int,
        entity_type: str,
    ) -> list[MemoryCardSpec]:
        """Internal vector search implementation."""
        hits = self._vector_or_hybrid_search_hits_internal(
            query=None,
            query_vector=query_vector,
            top_k=top_k,
            entity_type=entity_type,
            namespace=None,
            channel="latest",
            document_kind=None,
            search_type=SearchType.VECTOR,
            hybrid_weights=(0.5, 0.5),
        )
        return [MemoryCardSpec.model_validate(hit.content or {}) for hit in hits]

    def _vector_or_hybrid_search_hits_internal(
        self,
        query: str | None,
        query_vector: list[float],
        top_k: int,
        entity_type: str,
        namespace: str | None,
        channel: str,
        document_kind: str | None,
        search_type: SearchType,
        hybrid_weights: tuple[float, float] = (0.5, 0.5),
    ) -> list[SearchHitData]:
        """Internal vector or hybrid search implementation returning raw hits."""
        payload = {
            "search_type": search_type.value,
            "query_vector": query_vector,
            "top_k": top_k,
            "entity_type": entity_type,
            "channel": channel,
        }
        if namespace:
            payload["namespace"] = namespace
        if query is not None:
            payload["query"] = query
        if document_kind:
            payload["document_kind"] = document_kind
        if search_type == SearchType.HYBRID:
            payload["hybrid_weights"] = list(hybrid_weights)

        resp = self._http.post(
            "/v1/search/unified",
            json=payload,
        )
        data = self._handle_response(resp)
        return [SearchHitData.model_validate(hit) for hit in data["hits"]]

    def _bm25_search_hits_internal(
        self,
        query: str,
        top_k: int,
        entity_type: str,
        namespace: str | None,
        channel: str,
        document_kind: str | None,
    ) -> list[SearchHitData]:
        """Internal BM25 search implementation returning raw hits."""
        payload: dict[str, Any] = {
            "search_type": "bm25",
            "query": query,
            "top_k": top_k,
            "entity_type": entity_type,
            "channel": channel,
        }
        if namespace:
            payload["namespace"] = namespace
        if document_kind:
            payload["document_kind"] = document_kind
        resp = self._http.post(
            "/v1/search/unified",
            json=payload,
        )
        data = self._handle_response(resp)
        return [SearchHitData.model_validate(hit) for hit in data["hits"]]

    def get_facets(self, namespace: str | None = None) -> FacetsResponse:
        """Get aggregated facet counts for UI filters.

        Args:
            namespace: Optional namespace filter

        Returns:
            FacetsResponse with counts for entity_types, tags, authors, namespaces
        """
        params = {"namespace": namespace} if namespace else None
        resp = self._http.get("/v1/search/facets", params=params)
        data = self._handle_response(resp)
        return FacetsResponse.model_validate(data)


# =============================================================================
# Version Mixin
# =============================================================================


class VersionMixin(BaseMemoryClient):
    """Mixin providing version management operations.

    This mixin provides methods for:
    - Listing entity versions
    - Retrieving specific versions
    - Computing diffs between versions
    - Reverting to previous versions
    - Managing version channels (pin, promote)
    """

    def list_versions(
        self,
        entity_id: str,
        entity_type: str = "chain",
        limit: int = 20,
    ) -> list[VersionInfo]:
        """List all versions of an entity.

        Args:
            entity_id: Unique identifier for the entity
            entity_type: Type of entity (chain, step, agent, memory_card)
            limit: Maximum number of versions to return

        Returns:
            List of VersionInfo objects
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.get(f"/v1/{plural}/{entity_id}/versions", params={"limit": limit})
        data = self._handle_response(resp)
        return [VersionInfo.model_validate(v) for v in data]

    def get_version(
        self,
        entity_id: str,
        version_id: str,
        entity_type: str = "chain",
    ) -> VersionDetail:
        """Get a specific version with its full content.

        Args:
            entity_id: Unique identifier for the entity
            version_id: Version identifier
            entity_type: Type of entity (chain, step, agent, memory_card)

        Returns:
            VersionDetail with content and metadata
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.get(f"/v1/{plural}/{entity_id}/versions/{version_id}")
        data = self._handle_response(resp)
        return VersionDetail.model_validate(data)

    def diff_versions(
        self,
        entity_id: str,
        from_version: str,
        to_version: str,
        entity_type: str = "chain",
    ) -> DiffResponse:
        """Compute a JSON patch diff between two versions.

        Args:
            entity_id: Unique identifier for the entity
            from_version: Source version ID
            to_version: Target version ID
            entity_type: Type of entity (chain, step, agent, memory_card)

        Returns:
            DiffResponse with JSON patch
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.get(f"/v1/{plural}/{entity_id}/diff", params={"from": from_version, "to": to_version})
        data = self._handle_response(resp)
        return DiffResponse.model_validate(data)

    def revert(
        self,
        entity_id: str,
        target_version_id: str,
        entity_type: str = "chain",
    ) -> EntityRef:
        """Revert an entity by creating a new version with content from an old version.

        Args:
            entity_id: Unique identifier for the entity
            target_version_id: Version ID to revert to
            entity_type: Type of entity (chain, step, agent, memory_card)

        Returns:
            EntityRef for the new version
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.post(f"/v1/{plural}/{entity_id}/revert", json={"target_version_id": target_version_id})
        data = self._handle_response(resp)
        return EntityRef.model_validate(data)

    def pin_channel(
        self,
        entity_id: str,
        channel: str,
        version_id: str,
        entity_type: str = "chain",
    ) -> dict:
        """Pin a channel to a specific version.

        Args:
            entity_id: Unique identifier for the entity
            channel: Channel name to pin (latest, stable, custom)
            version_id: Version ID to pin the channel to
            entity_type: Type of entity (chain, step, agent, memory_card)

        Returns:
            Response dictionary
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.post(f"/v1/{plural}/{entity_id}/pin", json={"channel": channel, "version_id": version_id})
        return self._handle_response(resp)

    def promote(
        self,
        entity_id: str,
        from_channel: str = "latest",
        to_channel: str = "stable",
        entity_type: str = "chain",
    ) -> dict:
        """Promote: copy one channel pointer to another.

        Args:
            entity_id: Unique identifier for the entity
            from_channel: Source channel
            to_channel: Target channel
            entity_type: Type of entity (chain, step, agent, memory_card)

        Returns:
            Response dictionary
        """
        plural = _TYPE_PLURAL.get(entity_type, entity_type + "s")
        resp = self._http.post(
            f"/v1/{plural}/{entity_id}/promote", json={"from_channel": from_channel, "to_channel": to_channel}
        )
        return self._handle_response(resp)


# =============================================================================
# Main MemoryClient Class
# =============================================================================


class MemoryClient(SearchMixin, VersionMixin, ChainsMixin, AgentsMixin, MemoryCardsMixin):
    """Python client for the GigaEvo Memory Module API.

    Returns native CARL objects (ReasoningChain, typed steps) for chain/step
    entities, and Pydantic models for agent/memory_card entities.
    Raw dict accessors are also available via ``get_chain_dict()`` etc.

    The client uses multiple inheritance to compose functionality from mixins:
    - SearchMixin: Unified search, batch search, and facets
    - VersionMixin: Version management operations
    - ChainsMixin: Chain and step CRUD operations
    - AgentsMixin: Agent CRUD operations
    - MemoryCardsMixin: Memory card CRUD operations

    Example:
        >>> from gigaevo_memory import MemoryClient
        >>> client = MemoryClient(base_url="http://localhost:8000")
        >>> chain = client.get_chain("chain-id", channel="stable")
        >>> results = client.search("financial analysis", entity_type="memory_card")
        >>> client.close()

    Context manager usage:
        >>> with MemoryClient() as client:
        ...     chain = client.get_chain("chain-id")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        cache_policy: CachePolicy = CachePolicy.TTL,
        cache_ttl: int = 300,
        timeout: float = 30.0,
        freshness_on_miss: bool = False,
        sse_prefetch: bool = False,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        """Initialize the MemoryClient.

        Args:
            base_url: Base URL of the Memory API server
            cache_policy: Caching strategy (TTL, FRESHNESS_CHECK, SSE_PUSH)
            cache_ttl: Time-to-live for TTL cache in seconds
            timeout: HTTP request timeout in seconds
            freshness_on_miss: Whether to perform freshness check on cache miss
            sse_prefetch: Whether to prefetch entities via SSE
            embedding_provider: Optional provider for client-side embeddings
        """
        SearchMixin.__init__(
            self,
            base_url=base_url,
            cache_policy=cache_policy,
            cache_ttl=cache_ttl,
            timeout=timeout,
            freshness_on_miss=freshness_on_miss,
            sse_prefetch=sse_prefetch,
            embedding_provider=embedding_provider,
        )

    # =========================================================================
    # Watch (hot-swap)
    # =========================================================================

    def watch_chain(self, entity_id: str, callback: Any) -> Any:
        """Subscribe to SSE updates for a chain and call callback on changes.

        This method creates a background subscription that listens for
        Server-Sent Events (SSE) from the Memory API and invokes the
        callback whenever the chain is updated.

        Args:
            entity_id: Unique identifier for the chain to watch
            callback: Function to call when the chain changes

        Returns:
            Subscription object that can be stopped via ``sub.stop()``

        Example:
            >>> def on_update(new_chain):
            ...     print(f"Chain updated: {new_chain.metadata}")
            >>> sub = client.watch_chain("chain-id", callback=on_update)
            >>> # ... later ...
            >>> sub.stop()
        """
        from .watcher import Subscription

        sub = Subscription(self, entity_id=entity_id, entity_type="chain", callback=callback)
        sub.start()
        return sub

    # =========================================================================
    # Health & Maintenance
    # =========================================================================

    def health_check(self) -> dict[str, Any]:
        """Check API and dependency health.

        Returns:
            Dictionary with health status of API and dependencies (postgres, redis, etc.)
        """
        resp = self._http.get("/health")
        return self._handle_response(resp)

    def clear_all(self, entity_type: str | None = None) -> dict[str, int]:
        """Clear all entities, optionally filtered by type.

        WARNING: This is a destructive operation. Use with caution.

        Args:
            entity_type: Optional entity type to clear (chain, step, agent, memory_card).
                         If not provided, clears all entity types.

        Returns:
            Dictionary with counts of deleted entities per type
        """
        params = {"entity_type": entity_type} if entity_type else None
        resp = self._http.post("/v1/maintenance/clear-all", params=params)
        return self._handle_response(resp)

    # =========================================================================
    # Context manager
    # =========================================================================

    def __enter__(self) -> MemoryClient:
        """Context manager entry - returns self."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit - ensures HTTP client is closed."""
        self.close()


# Re-export _TYPE_PLURAL for backward compatibility
__all__ = ["MemoryClient", "_TYPE_PLURAL"]
