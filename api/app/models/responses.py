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
    version_number: int | None = None
    channel: str
    etag: str
    meta: dict[str, Any]
    content: dict[str, Any]
    # CARE library metadata (added in migration 003). All optional so
    # existing route handlers that don't populate them still emit valid
    # responses; CARE clients read them when present.
    favourite: bool = False
    run_count: int = 0
    last_run_at: datetime | None = None
    display_name: str | None = None
    description: str | None = None


class CursorPageResponse(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class StepResponse(EntityResponse):
    entity_type: Literal["step"] = "step"


class ChainResponse(EntityResponse):
    entity_type: Literal["chain"] = "chain"


class AgentResponse(EntityResponse):
    entity_type: Literal["agent"] = "agent"


class AgentSkillResponse(EntityResponse):
    entity_type: Literal["agent_skill"] = "agent_skill"


class MemoryCardResponse(EntityResponse):
    entity_type: Literal["memory_card"] = "memory_card"


class StepPageResponse(CursorPageResponse):
    items: list[StepResponse] = Field(default_factory=list)


class ChainPageResponse(CursorPageResponse):
    items: list[ChainResponse] = Field(default_factory=list)


class AgentPageResponse(CursorPageResponse):
    items: list[AgentResponse] = Field(default_factory=list)


class AgentSkillPageResponse(CursorPageResponse):
    items: list[AgentSkillResponse] = Field(default_factory=list)


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


class BulkSaveItemResult(BaseModel):
    """Per-item outcome inside a `BulkSaveResponse`.

    On success: `entity_ref` carries the persisted entity_id +
    version_id. On failure: `error` carries a short message and the
    response is otherwise empty.
    """

    index: int = Field(..., description="0-based position in the request `items` array.")
    success: bool
    entity_ref: dict[str, str] | None = Field(
        default=None,
        description=(
            "`{entity_id, entity_type, version_id, channel}` when "
            "`success=True`. Shape mirrors the typed-router responses "
            "so callers can drive follow-up requests without a separate "
            "GET."
        ),
    )
    error: str | None = Field(
        default=None,
        description="Short, human-readable failure reason when `success=False`.",
    )


class BulkSaveResponse(BaseModel):
    """Aggregate outcome for `POST /v1/bulk/save`."""

    results: list[BulkSaveItemResult] = Field(default_factory=list)
    success_count: int = 0
    error_count: int = 0


class LineageVersion(BaseModel):
    """A single node in an entity's ancestry DAG.

    Returned by ``GET /v1/chains/{id}/lineage`` and used by CARE's
    library evolution-tree visualisation. Carries the version's own
    `parents` array so the client can rebuild the full DAG topology
    without re-fetching.
    """

    version_id: str
    version_number: int
    parents: list[str] = Field(default_factory=list)
    evolution_meta: dict[str, Any] | None = None
    change_summary: str | None = None
    author: str | None = None
    created_at: datetime
    depth: int = Field(
        default=0,
        description=(
            "BFS depth from the requested root (0 = the root itself, "
            "1 = its direct parents, …). Convenient for layered "
            "rendering."
        ),
    )


class LineageResponse(BaseModel):
    """Ancestry DAG starting from a specific version (the ``root``).

    Versions are returned in BFS order (root first, then its parents,
    then their parents, …), de-duplicated by ``version_id``. ``depth``
    on each node lets clients render layers without re-walking.
    """

    entity_id: str
    root_version_id: str
    versions: list[LineageVersion] = Field(default_factory=list)
    max_depth_reached: bool = Field(
        default=False,
        description=(
            "True when the BFS hit ``max_depth`` and didn't fully "
            "expand all parents. The client may re-issue with a larger "
            "``max_depth`` to walk further."
        ),
    )


class DiffResponse(BaseModel):
    from_version: str
    to_version: str
    patch: dict[str, Any]


class VersionScore(BaseModel):
    """A single version's score on a chosen objective, plus its delta
    against the baseline channel.

    Returned inside :class:`DifferentialChannelView.winners`. The list
    is sorted by ``value`` (descending by default), so consumers can
    render "top N improvements" without a client-side sort.
    """

    version_id: str
    version_number: int
    value: float = Field(
        description="The version's recorded value for the requested objective."
    )
    delta: float = Field(
        description=(
            "``value`` minus the baseline channel's value. Always "
            "positive for entries in :class:`DifferentialChannelView.winners` "
            "(strict ``>`` filter)."
        ),
    )
    author: str | None = None
    created_at: datetime
    change_summary: str | None = None


class DuplicateMember(BaseModel):
    """One side of a near-duplicate pair."""

    entity_id: str
    version_id: str
    name: str
    display_name: str | None = None
    namespace: str | None = None


class DuplicatePair(BaseModel):
    """A pair of entities flagged as semantically near-duplicate.

    The pair is canonicalised: ``entity_a.entity_id < entity_b.entity_id``
    (lexicographic UUID order), so a deduplication walker can assume
    each unordered pair appears at most once in the response.
    """

    entity_a: DuplicateMember
    entity_b: DuplicateMember
    similarity: float = Field(
        ge=0.0,
        le=1.0,
        description="Cosine similarity in [0, 1]. Strictly ≥ the response's `threshold`.",
    )
    suggestion: str = Field(
        default="merge",
        description="Hint for catalogue maintenance — currently always `merge`.",
    )


class DuplicatesResponse(BaseModel):
    """Near-duplicate pairs returned by
    `GET /v1/{entity_type}/duplicates`. CARE / MAGE use it for
    catalogue hygiene — surface chains or skills that drift toward
    each other so a human can merge them.

    Requires the deployment to have ``ENABLE_VECTOR_SEARCH=true``
    (the endpoint 503s otherwise). Pairs are ordered by descending
    similarity so the most likely merge candidates surface first.
    """

    entity_type: str
    channel: str
    threshold: float = Field(
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity used to filter pairs (inclusive).",
    )
    pairs: list[DuplicatePair] = Field(default_factory=list)


class DifferentialChannelView(BaseModel):
    """Versions that beat a baseline channel on a specific objective.

    Powered by `GET /v1/chains/{id}/versions/beating`. CARE renders
    this as a "candidates for promotion" list — versions that
    outperform the currently-pinned `stable` channel on the chosen
    objective and may be worth a manual promotion decision.

    ``objective`` selects which metric to compare:

    * ``"fitness_score"`` (default) reads ``evolution_meta.fitness_score``,
      falling back to the legacy gigaevo-core ``fitness`` alias.
    * Any other string is looked up in ``evolution_meta.objectives``
      (e.g. ``"accuracy"``, ``"latency_ms"``).
    """

    entity_id: str
    baseline_channel: str
    baseline_version_id: str | None = Field(
        default=None,
        description=(
            "Version currently pinned to ``baseline_channel``. ``None`` "
            "when the channel isn't pinned for this entity."
        ),
    )
    objective: str
    baseline_value: float | None = Field(
        default=None,
        description=(
            "The baseline channel's recorded value for the chosen "
            "objective. ``None`` when no value is available — in that "
            "case ``winners`` is also empty (the comparison is "
            "ill-defined)."
        ),
    )
    winners: list[VersionScore] = Field(default_factory=list)


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
    """Response for unified search (BM25, vector, or hybrid)."""

    hits: list[SearchHit] = Field(default_factory=list)
    search_type: str = Field(
        description="Type of search performed (bm25, vector, or hybrid)"
    )
    total: int = Field(description="Total number of hits returned")
