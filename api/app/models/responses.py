"""Pydantic response schemas for the Memory API."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Strategy(str, Enum):
    """Strategy type for evolutionary memory cards."""

    EXPLORATION = "exploration"
    EXPLOITATION = "exploitation"
    HYBRID = "hybrid"


class EvolutionStatistics(BaseModel):
    """Evolutionary statistics for a memory card."""

    gain: float | None = None
    best_quartile: str | None = None
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


class EntityResponse(BaseModel):
    entity_type: str
    entity_id: str
    version_id: str
    channel: str
    etag: str
    meta: dict[str, Any]
    content: dict[str, Any]


class CursorPageResponse(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class StepResponse(EntityResponse):
    entity_type: Literal["step"] = "step"


class ChainResponse(EntityResponse):
    entity_type: Literal["chain"] = "chain"


class AgentResponse(EntityResponse):
    entity_type: Literal["agent"] = "agent"


class MemoryCardResponse(EntityResponse):
    entity_type: Literal["memory_card"] = "memory_card"


class StepPageResponse(CursorPageResponse):
    items: list[StepResponse] = Field(default_factory=list)


class ChainPageResponse(CursorPageResponse):
    items: list[ChainResponse] = Field(default_factory=list)


class AgentPageResponse(CursorPageResponse):
    items: list[AgentResponse] = Field(default_factory=list)


class MemoryCardPageResponse(CursorPageResponse):
    items: list[MemoryCardResponse] = Field(default_factory=list)


class VersionInfo(BaseModel):
    version_id: str
    entity_id: str
    version_number: int
    author: str | None = None
    change_summary: str | None = None
    evolution_meta: dict[str, Any] | None = None
    parents: list[str] | None = None
    created_at: datetime


class VersionDetail(VersionInfo):
    content: dict[str, Any]
    meta: dict[str, Any] | None = None


class DiffResponse(BaseModel):
    from_version: str
    to_version: str
    patch: dict[str, Any]


class SearchHit(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    score: float = 0.0
    channel: str | None = None
    version_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    when_to_use: str | None = None
    content: dict[str, Any] | None = None
    document_id: str | None = None
    document_kind: str | None = None
    snippet: str | None = None


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    total: int
    offset: int = 0
    limit: int = 20


class FacetsResponse(BaseModel):
    entity_types: dict[str, int] = Field(default_factory=dict)
    tags: dict[str, int] = Field(default_factory=dict)
    authors: dict[str, int] = Field(default_factory=dict)
    namespaces: dict[str, int] = Field(default_factory=dict)


class VectorSearchResponse(BaseModel):
    hits: list[SearchHit] = Field(default_factory=list)


class UnifiedSearchResponse(BaseModel):
    """Response for unified search (BM25 or vector)."""

    hits: list[SearchHit] = Field(default_factory=list)
    search_type: str = Field(description="Type of search performed (bm25 or vector)")
    total: int = Field(description="Total number of hits returned")
