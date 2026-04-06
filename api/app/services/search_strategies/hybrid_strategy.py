"""Hybrid search strategy combining BM25 and Vector scores."""

from __future__ import annotations

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from .base import SearchHit, SearchRequest, SearchStrategy
from .bm25_strategy import BM25SearchStrategy
from .vector_strategy import VectorSearchStrategy


class HybridSearchStrategy(SearchStrategy):
    """Hybrid search combining BM25 and Vector scores.

    Runs both searches in parallel, normalizes scores to [0, 1],
    and merges results with weighted combination.
    """

    def __init__(
        self,
        db: AsyncSession,
        embedding_service=None,  # Will be injected later
    ):
        """Initialize the hybrid strategy.

        Args:
            db: Database session
            embedding_service: Embedding service for server-side embedding
        """
        super().__init__(db)
        self._bm25_strategy = BM25SearchStrategy(db)
        self._vector_strategy = VectorSearchStrategy(db)
        self._embedding_service = embedding_service

    async def search(self, request: SearchRequest) -> list[SearchHit]:
        """Execute hybrid search.

        Combines BM25 and Vector scores with configurable weights.

        Args:
            request: Search request with hybrid_weights

        Returns:
            List of search hits with combined scores
        """
        # Extract weights
        bm25_weight, vector_weight = request.hybrid_weights

        # Normalize weights (ensure they sum to 1.0)
        total_weight = bm25_weight + vector_weight
        if total_weight == 0:
            bm25_weight = vector_weight = 0.5
        else:
            bm25_weight /= total_weight
            vector_weight /= total_weight

        # Run both searches in parallel
        bm25_request = SearchRequest(
            search_type=request.search_type,
            query=request.query,
            top_k=request.top_k * 2,  # Get more results for better merging
            entity_type=request.entity_type,
            tags=request.tags,
            namespace=request.namespace,
            channel=request.channel,
            document_kind=request.document_kind,
            hybrid_weights=request.hybrid_weights,
        )

        vector_request = SearchRequest(
            search_type=request.search_type,
            query=request.query,
            query_vector=request.query_vector,
            top_k=request.top_k * 2,  # Get more results for better merging
            entity_type=request.entity_type,
            tags=request.tags,
            namespace=request.namespace,
            channel=request.channel,
            document_kind=request.document_kind,
            hybrid_weights=request.hybrid_weights,
        )

        # Execute searches in parallel
        bm25_hits, vector_hits = await asyncio.gather(
            self._bm25_strategy.search(bm25_request),
            self._vector_strategy.search(vector_request),
        )

        # Normalize scores to [0, 1]
        bm25_hits_normalized = self._normalize_scores(bm25_hits)
        vector_hits_normalized = self._normalize_scores(vector_hits)

        # Merge results with weighted combination
        merged_hits = self._merge_results(
            bm25_hits_normalized,
            vector_hits_normalized,
            bm25_weight,
            vector_weight,
        )

        # Sort by combined score and return top_k
        merged_hits.sort(key=lambda h: h.score, reverse=True)
        return merged_hits[: request.top_k]

    def _normalize_scores(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Normalize scores to [0, 1] using min-max normalization.

        Args:
            hits: List of search hits

        Returns:
            List of hits with normalized scores
        """
        if not hits:
            return []

        scores = [hit.score for hit in hits]
        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            # All scores are the same, return 0.5 for all
            for hit in hits:
                hit.score = 0.5
        else:
            # Min-max normalization
            for hit in hits:
                hit.score = (hit.score - min_score) / (max_score - min_score)

        return hits

    def _merge_results(
        self,
        bm25_hits: list[SearchHit],
        vector_hits: list[SearchHit],
        bm25_weight: float,
        vector_weight: float,
    ) -> list[SearchHit]:
        """Merge results from both strategies with weighted scores.

        Args:
            bm25_hits: BM25 search results
            vector_hits: Vector search results
            bm25_weight: Weight for BM25 scores
            vector_weight: Weight for vector scores

        Returns:
            Merged list of hits with combined scores
        """
        # Create entity_id -> hit mapping
        bm25_map = {hit.entity_id: hit for hit in bm25_hits}
        vector_map = {hit.entity_id: hit for hit in vector_hits}

        # Get all unique entity_ids
        all_ids = set(bm25_map.keys()) | set(vector_map.keys())

        merged = []
        for entity_id in all_ids:
            bm25_hit = bm25_map.get(entity_id)
            vector_hit = vector_map.get(entity_id)

            # Calculate weighted score
            if bm25_hit and vector_hit:
                # Entity appears in both results
                score = (
                    bm25_hit.score * bm25_weight + vector_hit.score * vector_weight
                )
                hit = SearchHit(
                    entity_id=entity_id,
                    entity_type=bm25_hit.entity_type,
                    name=bm25_hit.name,
                    score=score,
                    channel=bm25_hit.channel,
                    version_id=bm25_hit.version_id,
                    tags=bm25_hit.tags,
                    when_to_use=bm25_hit.when_to_use,
                    content=bm25_hit.content,
                    document_id=vector_hit.document_id or bm25_hit.document_id,
                    document_kind=vector_hit.document_kind or bm25_hit.document_kind,
                    snippet=vector_hit.snippet or bm25_hit.snippet,
                )
            elif bm25_hit:
                # Only in BM25 results
                score = bm25_hit.score * bm25_weight
                hit = SearchHit(
                    entity_id=entity_id,
                    entity_type=bm25_hit.entity_type,
                    name=bm25_hit.name,
                    score=score,
                    channel=bm25_hit.channel,
                    version_id=bm25_hit.version_id,
                    tags=bm25_hit.tags,
                    when_to_use=bm25_hit.when_to_use,
                    content=bm25_hit.content,
                    document_id=bm25_hit.document_id,
                    document_kind=bm25_hit.document_kind,
                    snippet=bm25_hit.snippet,
                )
            else:
                # Only in vector results
                score = vector_hit.score * vector_weight
                hit = SearchHit(
                    entity_id=entity_id,
                    entity_type=vector_hit.entity_type,
                    name=vector_hit.name,
                    score=score,
                    channel=vector_hit.channel,
                    version_id=vector_hit.version_id,
                    tags=vector_hit.tags,
                    when_to_use=vector_hit.when_to_use,
                    content=vector_hit.content,
                    document_id=vector_hit.document_id,
                    document_kind=vector_hit.document_kind,
                    snippet=vector_hit.snippet,
                )

            merged.append(hit)

        return merged

    async def batch_search(
        self, request: SearchRequest, queries: list[str]
    ) -> list[list[SearchHit]]:
        """Execute batch hybrid search.

        Args:
            request: Base search request parameters
            queries: List of query texts

        Returns:
            List of result lists, one per query
        """
        results = []
        for query in queries:
            search_request = SearchRequest(
                search_type=request.search_type,
                query=query,
                query_vector=None,  # Will be set by embedding service
                top_k=request.top_k,
                entity_type=request.entity_type,
                tags=request.tags,
                namespace=request.namespace,
                channel=request.channel,
                document_kind=request.document_kind,
                hybrid_weights=request.hybrid_weights,
            )
            hits = await self.search(search_request)
            results.append(hits)
        return results
