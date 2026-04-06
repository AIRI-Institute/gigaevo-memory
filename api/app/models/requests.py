"""Pydantic request schemas for the Memory API."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SearchType(str, Enum):
    """Search algorithm type."""

    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid"


class Strategy(str, Enum):
    """Strategy type for evolutionary memory cards."""

    EXPLORATION = "exploration"
    EXPLOITATION = "exploitation"
    HYBRID = "hybrid"


class EntityMeta(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    tags: list[str] = Field(default_factory=list)
    when_to_use: str | None = None
    author: str | None = None
    namespace: str | None = None


class EvolutionMeta(BaseModel):
    mutation_kind: str | None = None
    prompt_ref: str | None = None
    fitness: float | None = None
    is_valid: bool | None = None
    metrics: dict[str, Any] | None = None
    behavioral_descriptors: dict[str, Any] | None = None


class EvolutionStatistics(BaseModel):
    """Evolutionary statistics for a memory card."""

    gain: float | None = None
    best_quartile: str | None = None  # "Q1" | "Q2" | "Q3" | "Q4"
    survival: int | None = None


class MemoryCardUsage(BaseModel):
    """Usage statistics for a memory card."""

    retrieved: int | None = None
    increased_fitness: float | None = None


class MemoryCardExplanation(BaseModel):
    """Rich explanation payload used by gigaevo-core memory cards."""

    explanations: list[str] = Field(default_factory=list)
    summary: str = ""


class MemoryCardContent(BaseModel):
    """Content schema for GigaEvo memory cards."""

    id: str | None = None
    category: str | None = None
    task_description: str | None = None
    task_description_summary: str | None = None
    description: str = ""
    explanation: str | MemoryCardExplanation = ""
    strategy: Strategy | None = None
    keywords: list[str] = Field(default_factory=list)
    evolution_statistics: EvolutionStatistics | dict[str, Any] | None = None
    works_with: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    usage: MemoryCardUsage | dict[str, Any] | None = None
    last_generation: int | None = None
    programs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    program_id: str | None = None
    fitness: float | None = None
    code: str | None = None
    connected_ideas: list[dict[str, Any]] = Field(default_factory=list)


class EntityCreateRequest(BaseModel):
    meta: EntityMeta
    channel: str = "latest"
    content: dict[str, Any]
    embedding: list[float] | None = None
    evolution_meta: EvolutionMeta | None = None
    parent_version_id: str | None = None


class EntityUpdateRequest(BaseModel):
    meta: EntityMeta | None = None
    channel: str = "latest"
    content: dict[str, Any]
    embedding: list[float] | None = None
    evolution_meta: EvolutionMeta | None = None
    parent_version_id: str | None = None
    change_summary: str | None = None


class VectorSearchRequest(BaseModel):
    query_vector: list[float]
    channel: str = "latest"
    entity_type: str | None = None
    tags: list[str] | None = None
    namespace: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class PinRequest(BaseModel):
    channel: str
    version_id: str


class RevertRequest(BaseModel):
    target_version_id: str


class PromoteRequest(BaseModel):
    from_channel: str = "latest"
    to_channel: str = "stable"


class UnifiedSearchRequest(BaseModel):
    """Request for unified search (BM25, vector, or hybrid)."""

    search_type: SearchType = Field(
        default=SearchType.BM25,
        description="Type of search: 'bm25', 'vector', or 'hybrid'",
    )
    query: str | None = Field(
        default=None,
        description="Text query for BM25 or hybrid search",
    )
    query_vector: list[float] | None = Field(
        default=None,
        description="Pre-computed embedding vector for vector search",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of top results to return",
    )
    entity_type: str = Field(
        default="memory_card",
        description="Type of entity to search",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Filter by tags",
    )
    namespace: str | None = Field(
        default=None,
        description="Filter by namespace",
    )
    channel: str = Field(
        default="latest",
        description="Version channel to search",
    )
    document_kind: str | None = Field(
        default=None,
        description="Optional memory-card search document kind to query",
    )
    hybrid_weights: tuple[float, float] = Field(
        default=(0.5, 0.5),
        description="(bm25_weight, vector_weight) for hybrid search, must sum to 1.0",
    )


class BatchSearchRequest(BaseModel):
    """Request for batch search."""

    search_type: SearchType = Field(
        default=SearchType.BM25,
        description="Type of search",
    )
    queries: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of search queries",
    )
    query_vectors: list[list[float]] | None = Field(
        default=None,
        description="Pre-computed embedding vectors for vector search",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of top results per query",
    )
    entity_type: str = Field(
        default="memory_card",
        description="Type of entity to search",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Filter by tags",
    )
    namespace: str | None = Field(
        default=None,
        description="Filter by namespace",
    )
    channel: str = Field(
        default="latest",
        description="Version channel to search",
    )
    document_kind: str | None = Field(
        default=None,
        description="Optional memory-card search document kind to query",
    )
    hybrid_weights: tuple[float, float] = (0.5, 0.5)
