"""Base classes for search strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession


class SearchType(str, Enum):
    """Search algorithm type."""

    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid"


class SearchRequest(BaseModel):
    """Request parameters for search operations."""

    search_type: SearchType
    query: str | None = None
    query_vector: list[float] | None = None
    top_k: int = 10
    entity_type: str = "memory_card"
    tags: list[str] | None = None
    namespace: str | None = None
    channel: str = "latest"
    document_kind: str | None = None
    hybrid_weights: tuple[float, float] = (0.5, 0.5)  # (bm25_weight, vector_weight)


class SearchHit(BaseModel):
    """A single search result hit."""

    entity_id: str
    entity_type: str
    name: str
    score: float
    channel: str | None
    version_id: str | None
    tags: list[str]
    when_to_use: str | None
    content: dict[str, Any] | None
    document_id: str | None = None
    document_kind: str | None = None
    snippet: str | None = None


class SearchContext:
    """Shared context for search operations.

    Contains database session and utility methods shared across strategies.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def build_filters(
        self,
        entity_type: str,
        tags: list[str] | None = None,
        namespace: str | None = None,
    ) -> list[str]:
        """Build SQL filter conditions.

        Args:
            entity_type: Type of entity to search
            tags: Optional tags filter
            namespace: Optional namespace filter

        Returns:
            List of SQL filter conditions
        """
        filters = [
            "e.deleted_at IS NULL",
            "e.entity_type = :entity_type",
        ]

        if namespace:
            filters.append("e.namespace = :namespace")

        if tags:
            # Tag filtering will be handled by caller
            pass

        return filters

    def format_hit(
        self,
        entity_id: UUID | str,
        entity_type: str,
        name: str,
        score: float,
        channel: str | None,
        version_id: UUID | str | None,
        tags: list[str],
        when_to_use: str | None,
        content: dict[str, Any] | None = None,
        document_id: UUID | str | None = None,
        document_kind: str | None = None,
        snippet: str | None = None,
    ) -> SearchHit:
        """Format a search hit from database results.

        Args:
            entity_id: Entity UUID
            entity_type: Entity type
            name: Entity name
            score: Search score
            channel: Version channel
            version_id: Version UUID
            tags: Entity tags
            when_to_use: When to use text
            content: Full content dict

        Returns:
            Formatted SearchHit
        """
        return SearchHit(
            entity_id=str(entity_id),
            entity_type=entity_type,
            name=name,
            score=float(score),
            channel=channel,
            version_id=str(version_id) if version_id else None,
            tags=tags or [],
            when_to_use=when_to_use,
            content=content,
            document_id=str(document_id) if document_id else None,
            document_kind=document_kind,
            snippet=snippet,
        )


class SearchStrategy(ABC):
    """Abstract base class for search strategies.

    Each search type (BM25, Vector, Hybrid) implements this interface.
    """

    def __init__(self, db: AsyncSession):
        """Initialize the strategy.

        Args:
            db: Database session
        """
        self.db = db
        self.context = SearchContext(db)

    @abstractmethod
    async def search(self, request: SearchRequest) -> list[SearchHit]:
        """Execute a single search.

        Args:
            request: Search request parameters

        Returns:
            List of search hits ranked by relevance
        """
        ...

    @abstractmethod
    async def batch_search(self, request: SearchRequest, queries: list[str]) -> list[list[SearchHit]]:
        """Execute batch search for multiple queries.

        Args:
            request: Search request parameters (base)
            queries: List of query texts

        Returns:
            List of result lists, one per query
        """
        ...
