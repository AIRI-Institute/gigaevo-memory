"""Pydantic models and TypedDicts for the gigaevo-memory client."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


# === Enums ===


class Strategy(str, Enum):
    """Strategy type for evolutionary memory cards."""

    EXPLORATION = "exploration"
    EXPLOITATION = "exploitation"
    HYBRID = "hybrid"


# === Pydantic models (shared, no CARL dependency) ===


class EntityRef(BaseModel):
    """Reference to an entity in the memory module."""

    entity_id: str
    entity_type: str
    version_id: str | None = None
    channel: str | None = None


class EntityResponse(BaseModel):
    """Full entity response from the API."""

    entity_type: str
    entity_id: str
    version_id: str
    channel: str
    etag: str
    meta: dict[str, Any]
    content: dict[str, Any]


class VersionInfo(BaseModel):
    """Version metadata (without content)."""

    version_id: str
    entity_id: str
    version_number: int
    author: str | None = None
    change_summary: str | None = None
    evolution_meta: dict[str, Any] | None = None
    parents: list[str] | None = None
    created_at: datetime

    @property
    def version_label(self) -> str:
        """Human-readable version label like 'v0', 'v1', etc."""
        return f"v{self.version_number}"


class ToolManifest(BaseModel):
    """Descriptor for an agent's tool (metadata only, not code)."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


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


class AgentSpec(BaseModel):
    """Agent specification — composition of chain + runtime settings."""

    name: str
    description: str = ""
    chain_ref: EntityRef
    system_prompt: str | None = None
    default_model: str | None = None
    max_workers: int = 3
    tool_manifests: list[ToolManifest] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    when_to_use: str | None = None


class MemoryCardSpec(BaseModel):
    """MemoryCard specification — GigaEvo memory card for evolutionary ideas/patterns."""

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


# === TypedDicts for raw mode (no CARL dependency) ===


class ChainDict(TypedDict, total=False):
    """Raw chain representation (matches chain_to_content() output)."""

    version: str
    max_workers: int
    enable_progress: bool
    metadata: dict
    search_config: dict
    steps: list[dict]


class StepDict(TypedDict, total=False):
    """Raw step representation."""

    number: int
    title: str
    dependencies: list[int]
    step_type: str  # "llm" | "tool" | "mcp" | "memory" | "transform" | "conditional" | "structured_output"
    step_config: dict | None
    aim: str
    reasoning_questions: str
    step_context_queries: list[dict[str, Any] | str]
    stage_action: str
    example_reasoning: str
    llm_config: dict | None
    retry_max: int | None  # Override retry attempts for this step
    timeout: float | None  # Timeout for this step in seconds


AgentDict = dict
MemoryCardDict = dict


class DiffResponse(BaseModel):
    """JSON diff between two versions."""

    from_version: str
    to_version: str
    patch: dict[str, Any]


class VersionDetail(BaseModel):
    """Version metadata with content."""

    version_id: str
    entity_id: str
    version_number: int
    author: str | None = None
    change_summary: str | None = None
    evolution_meta: dict[str, Any] | None = None
    parents: list[str] | None = None
    created_at: datetime
    content: dict[str, Any]
    meta: dict[str, Any] | None = None

    @property
    def version_label(self) -> str:
        """Human-readable version label like 'v0', 'v1', etc."""
        return f"v{self.version_number}"


class FacetsResponse(BaseModel):
    """Faceted search counts."""

    entity_types: dict[str, int] = Field(default_factory=dict)
    tags: dict[str, int] = Field(default_factory=dict)
    authors: dict[str, int] = Field(default_factory=dict)
    namespaces: dict[str, int] = Field(default_factory=dict)


class SearchHitData(BaseModel):
    """Rich search hit returned by the Memory search API."""

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


class Subscription:
    """Placeholder for SSE subscription (actual impl in watcher.py)."""

    pass
