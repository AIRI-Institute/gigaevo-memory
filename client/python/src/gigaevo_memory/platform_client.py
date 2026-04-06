"""Lightweight memory-card client without chain/agent dependencies."""

from __future__ import annotations

from typing import Any

from ._base import BaseMemoryClient
from .cache import CachePolicy
from .embeddings import EmbeddingProvider, get_default_provider
from .memory_cards import MemoryCardsMixin
from .models import FacetsResponse, MemoryCardSpec, SearchHitData
from .search_types import SearchType


class SearchMixin(BaseMemoryClient):
    """Search operations for memory-card-focused clients."""

    def __init__(self, *args, embedding_provider: EmbeddingProvider | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._embedding_provider = embedding_provider

    def _get_embedding_provider(self) -> EmbeddingProvider:
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
        hits = self.search_hits(
            query=query,
            search_type=search_type,
            top_k=top_k,
            entity_type=entity_type,
            channel=channel,
            embedding_provider=embedding_provider,
            document_kind=document_kind,
            hybrid_weights=hybrid_weights,
            namespace=namespace,
        )
        return [MemoryCardSpec.model_validate(hit.content or {}) for hit in hits]

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
            query_vector = None
            provider = embedding_provider or self._embedding_provider
            if provider is not None:
                try:
                    query_vector = provider.embed_query(query)
                except Exception:
                    query_vector = None
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
        hit_batches = self.batch_search_hits(
            queries=queries,
            search_type=search_type,
            top_k=top_k,
            entity_type=entity_type,
            channel=channel,
            embedding_provider=embedding_provider,
            document_kind=document_kind,
            hybrid_weights=hybrid_weights,
            namespace=namespace,
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
            query_vectors = None
            provider = embedding_provider or self._embedding_provider
            if provider is not None:
                try:
                    query_vectors = provider.embed(queries)
                except Exception:
                    query_vectors = None
            if query_vectors is not None:
                payload["query_vectors"] = query_vectors
        if search_type == SearchType.HYBRID:
            payload["hybrid_weights"] = list(hybrid_weights)

        resp = self._http.post("/v1/search/batch", json=payload)
        data = self._handle_response(resp)
        return [[SearchHitData.model_validate(hit) for hit in hits] for hits in data["results"]]

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
        payload: dict[str, Any] = {
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

        resp = self._http.post("/v1/search/unified", json=payload)
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
        resp = self._http.post("/v1/search/unified", json=payload)
        data = self._handle_response(resp)
        return [SearchHitData.model_validate(hit) for hit in data["hits"]]

    def get_facets(self, namespace: str | None = None) -> FacetsResponse:
        params = {"namespace": namespace} if namespace else None
        resp = self._http.get("/v1/search/facets", params=params)
        data = self._handle_response(resp)
        return FacetsResponse.model_validate(data)


class PlatformMemoryClient(SearchMixin, MemoryCardsMixin):
    """Minimal client focused on memory-card CRUD and search."""

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
