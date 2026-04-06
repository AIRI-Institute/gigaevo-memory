"""Unified search service dispatcher using strategy pattern.

This service provides a unified interface for BM25, vector, and hybrid search
by delegating to appropriate strategy implementations.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.requests import SearchType
from ..services.search_strategies.base import SearchRequest, SearchHit
from ..services.search_strategies.bm25_strategy import BM25SearchStrategy
from ..services.search_strategies.hybrid_strategy import HybridSearchStrategy
from ..services.search_strategies.vector_strategy import VectorSearchStrategy

if TYPE_CHECKING:
    from .embedding_service import EmbeddingService


class UnifiedSearchService:
    """Unified search service dispatcher.

    This service delegates search operations to appropriate strategies
    based on the search_type parameter.
    """

    def __init__(self, db: AsyncSession, embedding_service: EmbeddingService | None = None):
        """Initialize the search service.

        Args:
            db: Database session
            embedding_service: Optional embedding service for server-side embeddings
        """
        self.db = db
        self._embedding_service = embedding_service

        # Initialize strategies
        self._strategies = {
            SearchType.BM25: BM25SearchStrategy(db),
            SearchType.VECTOR: VectorSearchStrategy(db),
            SearchType.HYBRID: HybridSearchStrategy(db, embedding_service),
        }

    async def search(
        self,
        search_type: SearchType,
        query: str | None = None,
        query_vector: list[float] | None = None,
        top_k: int = 10,
        entity_type: str = "memory_card",
        tags: list[str] | None = None,
        namespace: str | None = None,
        channel: str = "latest",
        document_kind: str | None = None,
        hybrid_weights: tuple[float, float] = (0.5, 0.5),
    ) -> list[dict]:
        """Execute a single search.

        Args:
            search_type: Type of search (bm25, vector, hybrid)
            query: Text query (for BM25/hybrid)
            query_vector: Pre-computed vector (for vector/hybrid)
            top_k: Number of results
            entity_type: Entity type to search
            tags: Optional tags filter
            namespace: Optional namespace filter
            channel: Version channel
            document_kind: Optional memory-card search document kind
            hybrid_weights: Weights for hybrid search

        Returns:
            List of search hits as dicts
        """
        # Get the appropriate strategy
        strategy = self._strategies[search_type]

        # Handle server-side embedding if needed
        if search_type in (SearchType.VECTOR, SearchType.HYBRID):
            if query and not query_vector and self._embedding_service:
                query_vector = await self._embedding_service.embed_query(query)

        # Build search request
        request = SearchRequest(
            search_type=search_type,
            query=query,
            query_vector=query_vector,
            top_k=top_k,
            entity_type=entity_type,
            tags=tags,
            namespace=namespace,
            channel=channel,
            document_kind=document_kind,
            hybrid_weights=hybrid_weights,
        )

        # Delegate to strategy
        hits = await strategy.search(request)

        # Convert to dicts for backward compatibility
        return [self._hit_to_dict(hit) for hit in hits]

    async def batch_search(
        self,
        search_type: SearchType,
        queries: list[str],
        query_vectors: list[list[float]] | None = None,
        top_k: int = 10,
        entity_type: str = "memory_card",
        tags: list[str] | None = None,
        namespace: str | None = None,
        channel: str = "latest",
        document_kind: str | None = None,
        hybrid_weights: tuple[float, float] = (0.5, 0.5),
    ) -> list[list[dict]]:
        """Execute batch search for multiple queries.

        Args:
            search_type: Type of search (bm25, vector, hybrid)
            queries: List of query texts
            query_vectors: Pre-computed vectors (for vector/hybrid)
            top_k: Number of results per query
            entity_type: Entity type to search
            tags: Optional tags filter
            namespace: Optional namespace filter
            channel: Version channel
            document_kind: Optional memory-card search document kind
            hybrid_weights: Weights for hybrid search

        Returns:
            List of result lists, one per query
        """
        if not queries:
            return []

        strategy = self._strategies[search_type]

        # Batch embed all queries if server-side embedding is needed
        if search_type in (SearchType.VECTOR, SearchType.HYBRID):
            if queries and not query_vectors and self._embedding_service:
                query_vectors = await self._embedding_service.embed_batch(queries)

        # Create search tasks for parallel execution
        tasks = []
        for idx, query in enumerate(queries):
            qv = query_vectors[idx] if query_vectors else None

            # Create search request
            request = SearchRequest(
                search_type=search_type,
                query=query,
                query_vector=qv,
                top_k=top_k,
                entity_type=entity_type,
                tags=tags,
                namespace=namespace,
                channel=channel,
                document_kind=document_kind,
                hybrid_weights=hybrid_weights,
            )

            tasks.append(strategy.search(request))

        # Execute all searches in parallel
        results = await asyncio.gather(*tasks)

        # Convert to dicts
        return [
            [self._hit_to_dict(hit) for hit in hits]
            for hits in results
        ]

    def _hit_to_dict(self, hit: SearchHit) -> dict:
        """Convert SearchHit to dict for backward compatibility.

        Args:
            hit: SearchHit object

        Returns:
            Dictionary representation
        """
        return {
            "entity_id": hit.entity_id,
            "entity_type": hit.entity_type,
            "name": hit.name,
            "score": hit.score,
            "channel": hit.channel,
            "version_id": hit.version_id,
            "tags": hit.tags,
            "when_to_use": hit.when_to_use,
            "content": hit.content,
            "document_id": hit.document_id,
            "document_kind": hit.document_kind,
            "snippet": hit.snippet,
        }
