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
    # CARE library metadata (server migration 003). All optional with
    # safe defaults so older Memory servers that don't emit these fields
    # still parse cleanly.
    favourite: bool = False
    run_count: int = 0
    last_run_at: datetime | None = None
    display_name: str | None = None
    description: str | None = None


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


class EvolutionMeta(BaseModel):
    """Client-side mirror of ``api/app/models/requests.py::EvolutionMeta``.

    Carries provenance + fitness metadata for an entity version produced
    by an evolutionary run (gigaevo-core / gigaevo-platform / CARE).
    See the server-side docstring for the full field reference.
    """

    # === CARE / Platform standardised shape (§5 P1) ===
    parent_version_ids: list[str] | None = None
    fitness_score: float | None = None
    generation: int | None = Field(default=None, ge=0)
    experiment_id: str | None = None
    objectives: dict[str, float] | None = None

    # === Legacy gigaevo-core shape (preserved for backward compat) ===
    mutation_kind: str | None = None
    prompt_ref: str | None = None
    fitness: float | None = None
    is_valid: bool | None = None
    metrics: dict[str, Any] | None = None
    behavioral_descriptors: dict[str, Any] | None = None


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


class ContextFileRef(BaseModel):
    """A file CARE attached as context at agent-generation time."""

    path: str
    sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    size_bytes: int = Field(..., ge=0)
    mime_type: str | None = None


class CareChainMetadata(BaseModel):
    """Standardised CARE-side keys inside ``chain.content_json["metadata"]``.

    Mirrors ``api/app/models/requests.py::CareChainMetadata`` (server
    side). CARE clients use this to construct the chain ``content``
    correctly so "Run again with same inputs" can re-prime the
    `ReasoningContext` deterministically.

    See ``docs/CHAIN_CONTENT_CONVENTIONS.md`` for the full spec.
    """

    task_description: str | None = None
    context_files: list[ContextFileRef] = Field(default_factory=list)
    generated_by: str | None = None
    mage_metadata: dict[str, Any] | None = None
    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_chain_content(cls, content: dict[str, Any]) -> "CareChainMetadata":
        """Extract a typed view from a chain's ``content_json``.

        Returns an empty ``CareChainMetadata`` when ``content`` does not
        carry a ``"metadata"`` block — keeps callers free of None-checks.
        """
        block = content.get("metadata") if isinstance(content, dict) else None
        if not isinstance(block, dict):
            return cls()
        return cls.model_validate(
            {k: v for k, v in block.items() if k in cls.model_fields}
        )

    def merge_into_content(self, content: dict[str, Any]) -> dict[str, Any]:
        """Return a new content dict with this CARE metadata applied.

        Preserves existing non-CARE keys in ``content["metadata"]``.
        """
        out = dict(content) if isinstance(content, dict) else {}
        existing = out.get("metadata", {}) if isinstance(out.get("metadata"), dict) else {}
        merged = dict(existing)
        merged.update(self.model_dump(exclude_none=True, exclude_defaults=False))
        out["metadata"] = merged
        return out


class AgentSkillSpec(BaseModel):
    """AgentSkill specification — a portable SKILL.md folder persisted to memory.

    Mirrors `api/app/models/requests.py::AgentSkillContent` (server side).
    CARE persists every resolved AgentSkill here so generated chains can
    reference the skill by stable `entity_id` and MAGE's capability
    lookup can search SKILL.md descriptions and bodies.
    """

    name: str = Field(..., min_length=1, max_length=200)
    description: str
    uri: str = Field(
        ...,
        description=(
            "Stable identifier: `github://owner/repo[/subpath][@ref]`, "
            "`local://`, `https://`, `module://pkg`, or a bare skill name."
        ),
    )
    sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="SHA-256 hex digest of the SKILL.md file.",
    )
    manifest: dict[str, Any] = Field(default_factory=dict)
    instructions: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    compatibility: dict[str, Any] | None = None
    tarball_url: str | None = None
    tarball_sha256: str | None = None


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
AgentSkillDict = dict
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


class LineageVersion(BaseModel):
    """A single node in an entity's ancestry DAG."""

    version_id: str
    version_number: int
    parents: list[str] = Field(default_factory=list)
    evolution_meta: dict[str, Any] | None = None
    change_summary: str | None = None
    author: str | None = None
    created_at: datetime
    depth: int = 0


class LineageResponse(BaseModel):
    """Ancestry DAG returned by ``GET /v1/chains/{id}/lineage``."""

    entity_id: str
    root_version_id: str
    versions: list[LineageVersion] = Field(default_factory=list)
    max_depth_reached: bool = False


class VersionScore(BaseModel):
    """A single version's score on a chosen objective, plus delta vs. baseline."""

    version_id: str
    version_number: int
    value: float
    delta: float
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

    The pair is canonicalised (``entity_a.entity_id < entity_b.entity_id``)
    so each unordered pair appears at most once in the response.
    """

    entity_a: DuplicateMember
    entity_b: DuplicateMember
    similarity: float
    suggestion: str = "merge"


class DuplicatesResponse(BaseModel):
    """Near-duplicate pairs returned by
    ``GET /v1/{entity_type}/duplicates``. Sorted by descending
    similarity. Requires the deployment to have vector search
    enabled (the endpoint 503s otherwise)."""

    entity_type: str
    channel: str
    threshold: float
    pairs: list[DuplicatePair] = Field(default_factory=list)


class DifferentialChannelView(BaseModel):
    """Versions that beat a baseline channel on a specific objective.

    Returned by ``GET /v1/chains/{id}/versions/beating``. CARE renders
    this as a "candidates for promotion" view — versions that scored
    higher than the currently-blessed channel pin on the chosen metric.
    """

    entity_id: str
    baseline_channel: str
    baseline_version_id: str | None = None
    objective: str
    baseline_value: float | None = None
    winners: list[VersionScore] = Field(default_factory=list)


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


class CapabilityHit(BaseModel):
    """A single capability MAGE could plug into a generated chain.

    Today every hit's ``entity_type`` is ``"agent_skill"``. MCP servers
    and tool registrations will get their own entity type later
    (Memory TODO §1.1 / future P2 work) — at which point hits of those
    types will land in the same ranked list and CARE / MAGE can
    discriminate by ``entity_type``.

    ``matched_via`` records which doc kind / search mode produced the
    hit so consumers can prefer high-signal matches
    (``"skill_description"`` is the cleanest BM25 input;
    ``"skill_instructions"`` runs against the full SKILL.md body).
    """

    entity_id: str
    entity_type: str = "agent_skill"
    name: str
    description: str | None = None
    score: float
    snippet: str | None = None
    tags: list[str] = Field(default_factory=list)
    matched_via: str | None = Field(
        default=None,
        description=(
            "Provenance of the match: ``skill_description``, "
            "``skill_instructions``, ``skill_full``, "
            "``skill_allowed_tools``, or ``generic`` when the search "
            "ran without a document_kind filter."
        ),
    )

    @classmethod
    def from_search_hit(
        cls,
        hit: "SearchHitData",
        *,
        fallback_matched_via: str = "generic",
    ) -> "CapabilityHit":
        """Project a generic ``SearchHitData`` onto the capability shape.

        Pulls ``description`` from ``content.description`` when the hit
        carries content, falls back to the doc snippet otherwise.
        """
        description = None
        if hit.content and isinstance(hit.content.get("description"), str):
            description = hit.content["description"]
        return cls(
            entity_id=hit.entity_id,
            entity_type=hit.entity_type,
            name=hit.name,
            description=description,
            score=hit.score,
            snippet=hit.snippet,
            tags=list(hit.tags),
            matched_via=hit.document_kind or fallback_matched_via,
        )


class Subscription:
    """Placeholder for SSE subscription (actual impl in watcher.py)."""

    pass
