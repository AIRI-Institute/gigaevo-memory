"""Unified search router: BM25, vector, and hybrid search with automatic embedding."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthContext, default_read_namespace_for, require_api_key
from ..config import settings
from ..db.session import get_db
from ..db.models import Entity
from ..models.requests import BatchSearchRequest, SearchType, UnifiedSearchRequest
from ..models.responses import (
    FacetsResponse,
    SearchHit,
    UnifiedSearchResponse,
    VectorSearchResponse,
)
from ..services.embedding_service import EmbeddingService
from ..services.unified_search_service import UnifiedSearchService

router = APIRouter()


async def get_embedding_service():
    """Get or create embedding service instance."""
    if settings.enable_vector_search:
        return await EmbeddingService.create()
    return None


def _effective_read_namespace(
    namespace: str | None,
    auth: AuthContext,
) -> str | None:
    """Resolve search namespace, treating blank input as omitted."""
    query_namespace = None if namespace is not None and not namespace.strip() else namespace
    return default_read_namespace_for(query_namespace, auth)


@router.post("/search/unified", response_model=UnifiedSearchResponse)
async def unified_search(
    body: UnifiedSearchRequest,
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
    embedding_service=Depends(get_embedding_service),
):
    """Unified search endpoint supporting BM25, vector, and hybrid search.

    This endpoint provides a single interface for three search types:
    - **bm25**: Full-text search using PostgreSQL tsvector
    - **vector**: Semantic search using pgvector similarity
    - **hybrid**: Combined BM25 + Vector scores with configurable weights

    For vector and hybrid search, embeddings can be generated server-side
    (if ENABLE_VECTOR_SEARCH=true) or provided as pre-computed vectors.

    Authenticated callers without an explicit ``namespace`` are
    auto-scoped to ``auth.owner`` unless they hold ``read:any``.
    Anonymous opt-in callers keep the existing unscoped behavior.

    Example BM25 request:
        {
            "search_type": "bm25",
            "query": "financial analysis",
            "top_k": 10,
            "entity_type": "memory_card"
        }

    Example vector request (server-side embedding):
        {
            "search_type": "vector",
            "query": "semantic similarity",
            "top_k": 10,
            "entity_type": "memory_card"
        }

    Example hybrid request:
        {
            "search_type": "hybrid",
            "query": "analysis",
            "hybrid_weights": [0.3, 0.7],
            "top_k": 10,
            "entity_type": "memory_card"
        }

    Example vector request (client-side embedding):
        {
            "search_type": "vector",
            "query_vector": [0.1, 0.2, ...],
            "top_k": 10,
            "entity_type": "memory_card"
        }
    """
    # Check vector search availability
    if body.search_type in (SearchType.VECTOR, SearchType.HYBRID):
        if not settings.enable_vector_search:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vector search is not enabled. Set ENABLE_VECTOR_SEARCH=true.",
            )

    # Create search service
    svc = UnifiedSearchService(db, embedding_service)

    try:
        # Validate request based on search_type
        if body.search_type == SearchType.BM25 and not body.query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="query is required for BM25 search",
            )

        if body.search_type == SearchType.VECTOR and not body.query and not body.query_vector:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either query or query_vector is required for vector search",
            )

        effective_namespace = _effective_read_namespace(body.namespace, auth)

        # Execute search
        hits = await svc.search(
            search_type=body.search_type,
            query=body.query,
            query_vector=body.query_vector,
            top_k=body.top_k,
            entity_type=body.entity_type,
            tags=body.tags,
            namespace=effective_namespace,
            channel=body.channel,
            document_kind=body.document_kind,
            requires_tool=body.requires_tool,
            excludes_tool=body.excludes_tool,
            hybrid_weights=body.hybrid_weights,
        )

        return UnifiedSearchResponse(
            hits=[SearchHit(**hit) for hit in hits],
            search_type=body.search_type,
            total=len(hits),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {str(exc)}",
        ) from exc


class BatchSearchResponseModel(BaseModel):
    """Response for batch search."""

    results: list[list[SearchHit]]
    search_type: SearchType
    total_queries: int


class VectorSearchRequest(BaseModel):
    """Backward-compatible BYO-vector search request."""

    query_vector: list[float] = Field(..., min_length=1)
    channel: str = "latest"
    limit: int = Field(default=10, ge=1, le=100)
    entity_type: str = "chain"
    tags: list[str] | None = None
    namespace: str | None = None


@router.post("/search/vector", response_model=VectorSearchResponse)
async def vector_search(
    body: VectorSearchRequest,
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
    embedding_service=Depends(get_embedding_service),
):
    """Compatibility endpoint for client-supplied vector search.

    New clients should prefer ``POST /v1/search/unified`` with
    ``search_type="vector"``. This endpoint keeps the older
    ``/v1/search/vector`` shape used by existing integrations.
    """
    if not settings.enable_vector_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector search is not enabled. Set ENABLE_VECTOR_SEARCH=true.",
        )

    svc = UnifiedSearchService(db, embedding_service)
    try:
        hits = await svc.search(
            search_type=SearchType.VECTOR,
            query_vector=body.query_vector,
            top_k=body.limit,
            entity_type=body.entity_type,
            tags=body.tags,
            namespace=_effective_read_namespace(body.namespace, auth),
            channel=body.channel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return VectorSearchResponse(hits=[SearchHit(**hit) for hit in hits])


@router.post("/search/batch", response_model=BatchSearchResponseModel)
async def batch_search(
    body: BatchSearchRequest,
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
    embedding_service=Depends(get_embedding_service),
):
    """Batch search for multiple queries.

    Batch-embeds vector inputs when needed, then runs DB-bound searches
    serially on the request-scoped session.
    Returns a list of result lists, one per query.

    Authenticated callers without an explicit ``namespace`` are
    auto-scoped to ``auth.owner`` unless they hold ``read:any``.
    Anonymous opt-in callers keep the existing unscoped behavior.

    Example request:
        {
            "search_type": "hybrid",
            "queries": ["financial analysis", "code review", "documentation"],
            "top_k": 5,
            "entity_type": "memory_card",
            "hybrid_weights": [0.4, 0.6]
        }
    """
    # Check vector search availability
    if body.search_type in (SearchType.VECTOR, SearchType.HYBRID):
        if not settings.enable_vector_search:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Vector search is not enabled. Set ENABLE_VECTOR_SEARCH=true.",
            )

    # Create search service
    svc = UnifiedSearchService(db, embedding_service)

    try:
        effective_namespace = _effective_read_namespace(body.namespace, auth)

        # Execute batch search
        results = await svc.batch_search(
            search_type=body.search_type,
            queries=body.queries,
            query_vectors=body.query_vectors,
            top_k=body.top_k,
            entity_type=body.entity_type,
            tags=body.tags,
            namespace=effective_namespace,
            channel=body.channel,
            document_kind=body.document_kind,
            requires_tool=body.requires_tool,
            excludes_tool=body.excludes_tool,
            hybrid_weights=body.hybrid_weights,
        )

        return BatchSearchResponseModel(
            results=[[SearchHit(**hit) for hit in hits] for hits in results],
            search_type=body.search_type,
            total_queries=len(body.queries),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch search error: {str(exc)}",
        ) from exc


@router.get("/search/facets", response_model=FacetsResponse)
async def get_facets(
    namespace: str | None = Query(None, description="Filter facets by namespace"),
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated facet counts for UI filters.

    Returns counts for:
    - entity_types: Number of entities per type
    - tags: Number of entities per tag
    - authors: Number of entities per author
    - namespaces: Number of entities per namespace

    Authenticated callers without an explicit ``namespace`` are
    auto-scoped to ``auth.owner`` unless they hold ``read:any``.
    Anonymous opt-in callers keep the existing unscoped behavior.
    """
    try:
        effective_namespace = _effective_read_namespace(namespace, auth)
        base_cond = [Entity.deleted_at.is_(None)]
        if effective_namespace is not None:
            base_cond.append(Entity.namespace == effective_namespace)

        # Entity type counts
        type_stmt = select(Entity.entity_type, func.count()).where(*base_cond).group_by(Entity.entity_type)
        type_result = await db.execute(type_stmt)
        entity_types = {row[0]: row[1] for row in type_result.all()}

        # Namespace counts
        ns_stmt = (
            select(Entity.namespace, func.count())
            .where(*base_cond, Entity.namespace.isnot(None))
            .group_by(Entity.namespace)
        )
        ns_result = await db.execute(ns_stmt)
        namespaces = {row[0]: row[1] for row in ns_result.all()}

        tag_sql = (
            "SELECT tag, COUNT(*) AS count "
            "FROM entities e "
            "CROSS JOIN LATERAL jsonb_array_elements_text(e.tags) AS tag "
            "WHERE e.deleted_at IS NULL"
        )
        tag_params: dict[str, str] = {}
        if effective_namespace is not None:
            tag_sql += " AND e.namespace = :namespace"
            tag_params["namespace"] = effective_namespace
        tag_sql += " GROUP BY tag ORDER BY tag"
        tag_result = await db.execute(text(tag_sql), tag_params)
        tags = {str(row[0]): int(row[1]) for row in tag_result.all()}

        return FacetsResponse(
            entity_types=entity_types,
            tags=tags,
            authors={},  # Empty for now - requires joining with entity_versions
            namespaces=namespaces,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Facets error: {str(exc)}",
        ) from exc
