"""Pydantic request schemas for the Memory API."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


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
    """Provenance + fitness metadata for an entity version produced by
    an evolutionary run (gigaevo-core / gigaevo-platform / CARE).

    Two concentric schemas live here:

    * **CARE / gigaevo-platform shape** (P1 §5, standardised 2026-05-16):
      ``parent_version_ids`` (UUIDs of the parents this version was
      mutated/crossed from), ``fitness_score`` (single-objective
      scalar in [0, 1] or wider — depends on fitness function),
      ``generation`` (0-indexed generation number), ``experiment_id``
      (the parent evolution run), ``objectives`` (multi-objective dict,
      e.g. ``{"accuracy": 0.91, "latency_ms": 1240, "tokens": 4200}``),
      ``mutation_kind`` (free string; typical values:
      ``"step_swap"``, ``"prompt_rewrite"``, ``"topology_change"``,
      ``"crossover"``, ``"manual_edit"``).
    * **Legacy gigaevo-core shape** (pre-2026-05): ``prompt_ref``,
      ``fitness``, ``is_valid``, ``metrics``, ``behavioral_descriptors``.
      Kept for backward compat — pre-existing rows decode without
      reshape. New callers should prefer the standardised fields.

    Every field is optional. Empty ``EvolutionMeta()`` is legal.
    """

    # === CARE / Platform standardised shape (§5 P1) ===
    parent_version_ids: list[str] | None = Field(
        default=None,
        description=(
            "UUIDs of the parent versions this version was derived from. "
            "Single-parent mutation has length 1; crossover has length ≥ 2."
        ),
    )
    fitness_score: float | None = Field(
        default=None,
        description="Single-objective scalar. Range depends on fitness function.",
    )
    generation: int | None = Field(
        default=None,
        ge=0,
        description="Zero-indexed generation number within the experiment.",
    )
    experiment_id: str | None = Field(
        default=None,
        description="Identifier for the parent gigaevo-platform experiment.",
    )
    objectives: dict[str, float] | None = Field(
        default=None,
        description=(
            "Multi-objective fitness dict — e.g. "
            '{"accuracy": 0.91, "latency_ms": 1240, "tokens": 4200}.'
        ),
    )

    # === Legacy gigaevo-core shape (preserved for backward compat) ===
    mutation_kind: str | None = Field(
        default=None,
        description=(
            "Mutation/cross-over kind that produced this version. "
            'Typical values: "step_swap", "prompt_rewrite", '
            '"topology_change", "crossover", "manual_edit".'
        ),
    )
    prompt_ref: str | None = None
    fitness: float | None = Field(
        default=None,
        description="Legacy alias for `fitness_score`. New callers prefer `fitness_score`.",
    )
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


class ContextFileRef(BaseModel):
    """A single file CARE attached as context at agent-generation time.

    Stored inside ``chain.content_json["metadata"]["context_files"]`` so
    the same files can be re-read when the user picks "Run again with
    same inputs" from the CARE library.
    """

    path: str = Field(..., description="Absolute or workspace-relative path at generation time.")
    sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="SHA-256 hex digest of the file contents.",
    )
    size_bytes: int = Field(..., ge=0)
    mime_type: str | None = Field(
        default=None,
        description="Optional MIME type (e.g. 'application/pdf'). Helpful when "
        "the path is missing an extension.",
    )


class CareChainMetadata(BaseModel):
    """Standardised CARE-side keys inside ``chain.content_json["metadata"]``.

    The Memory backend stores ``content`` as opaque JSON; this model
    documents the agreed key set used by CARE for re-run, library
    rendering, and provenance:

      * ``task_description`` — verbatim user query that prompted the
        agent. CARE re-primes the ``ReasoningContext.outer_context``
        from this on "Run with same inputs".
      * ``context_files``    — files the user attached at generation
        time, each with path + SHA + size for re-load validation.
      * ``generated_by``     — ``"mage"`` / ``"user"`` / custom string;
        free-form provenance tag.
      * ``mage_metadata``    — full ``MAGEMetadata.model_dump()`` from
        the upstream generation (domain, stages_completed, costs, etc.).
      * ``display_name``     — human-friendly label for the CARE
        library (same shape as ``Entity.display_name`` — duplicated
        here so a chain JSON dump is self-describing without joining
        against ``entities``).
      * ``description``      — free-form description (same role as
        ``Entity.description``).
      * ``tags``              — user-facing tags incl. ``"favourite"``.

    This is a **client-side validation aid**; routes still accept any
    JSON for forward compatibility.
    """

    task_description: str | None = None
    context_files: list[ContextFileRef] = Field(default_factory=list)
    generated_by: str | None = Field(
        default=None,
        description='Free-form provenance tag, e.g. "mage" or "user".',
    )
    mage_metadata: dict[str, Any] | None = None
    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_chain_content(cls, content: dict[str, Any]) -> "CareChainMetadata":
        """Parse a chain ``content_json`` dict and return a typed
        metadata view, ignoring keys that aren't part of the convention.

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
        """Return a new ``content`` dict with this metadata applied.

        Preserves all existing keys in ``content["metadata"]`` that fall
        outside the CARE-managed key set (e.g. chain-specific configs
        live alongside CARE metadata in the same block).
        """
        out = dict(content) if isinstance(content, dict) else {}
        existing = out.get("metadata", {}) if isinstance(out.get("metadata"), dict) else {}
        merged = dict(existing)
        merged.update(self.model_dump(exclude_none=True, exclude_defaults=False))
        out["metadata"] = merged
        return out


class AgentSkillContent(BaseModel):
    """Content schema for AgentSkill entities.

    An AgentSkill mirrors the on-disk structure of a portable
    [AgentSkills](https://agentskills.io) folder (SKILL.md + bundled
    scripts/assets), persisted into GigaEvo Memory so generated chains
    can reference the skill by stable `entity_id` and MAGE's capability
    lookup can search SKILL.md descriptions.

    The Memory backend stores `content` as opaque JSON; this model
    documents the agreed shape and gives the OpenAPI surface a typed
    component CARE / MAGE clients can validate against locally.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Skill name (matches SKILL.md frontmatter 'name').",
    )
    description: str = Field(
        ...,
        description="Human-readable summary of what the skill does.",
    )
    uri: str = Field(
        ...,
        description=(
            "Stable identifier the resolver dispatches on: "
            "`github://owner/repo[/subpath][@ref]`, `local://...`, "
            "`https://...`, `module://pkg`, or a bare skill name."
        ),
    )
    sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="SHA-256 hex digest of the SKILL.md file (lower or upper case).",
    )
    manifest: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parsed SKILL.md frontmatter (YAML). Keys include `name`, "
            "`description`, `license`, `compatibility`, plus skill-specific "
            "metadata."
        ),
    )
    instructions: str = Field(
        default="",
        description="The full SKILL.md body (everything after the frontmatter).",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Tokens parsed from the SKILL.md `allowed-tools` field "
            '(e.g. ["Bash(git:*)", "Read", "Write", '
            '"WebFetch(domain:api.example.com)"]).'
        ),
    )
    tags: list[str] = Field(default_factory=list)
    compatibility: dict[str, Any] | None = Field(
        default=None,
        description="Optional compatibility block from SKILL.md frontmatter.",
    )
    tarball_url: str | None = Field(
        default=None,
        description=(
            "For `github://` sources: the resolved "
            "`codeload.github.com/.../tar.gz/<ref>` URL the resolver "
            "downloaded."
        ),
    )
    tarball_sha256: str | None = Field(
        default=None,
        description="Optional SHA-256 of the resolved tarball for stronger pinning.",
    )


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


class FavouriteRequest(BaseModel):
    """Body for POST /v1/{type}/{id}/favourite — toggle or set the flag."""

    favourite: bool = True


class RecordRunRequest(BaseModel):
    """Body for POST /v1/{type}/{id}/run-recorded.

    `run_id` is currently informational (will be used to dedupe
    accidental double-recordings via a short-lived in-memory LRU). The
    field is optional; clients can omit it.
    """

    run_id: str | None = None


class BulkSaveItem(BaseModel):
    """One entity to persist in a bulk-save request.

    Carries `entity_type` (selects the routing) plus the same payload
    shape as `EntityCreateRequest` / `EntityUpdateRequest`. When
    `entity_id` is set, the item is upserted as a new version on that
    entity; otherwise a new entity is created.
    """

    entity_type: str = Field(
        ...,
        description=(
            "One of `step | chain | agent | agent_skill | memory_card` "
            "(singular form, matches `VALID_ENTITY_TYPES` values)."
        ),
    )
    meta: EntityMeta
    channel: str = "latest"
    content: dict[str, Any]
    embedding: list[float] | None = None
    evolution_meta: EvolutionMeta | None = None
    parent_version_id: str | None = None
    entity_id: str | None = Field(
        default=None,
        description=(
            "Set to upsert (creates a new version on the existing "
            "entity); omit to create a new entity."
        ),
    )
    change_summary: str | None = Field(
        default=None,
        description="Only used on the update path (when `entity_id` is set).",
    )


class BulkSaveRequest(BaseModel):
    """Body for `POST /v1/bulk/save`.

    Designed for CARE's `care import ./generated_chains/*.json` flow:
    a mixed list of entities (chains + agents + skills + memory_cards)
    submitted in one request to amortise HTTP round-trips. The server
    walks the list, persisting each item in its own transaction;
    per-item failures don't poison earlier successes.
    """

    items: list[BulkSaveItem] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Up to 500 entities per call.",
    )
    stop_on_error: bool = Field(
        default=False,
        description=(
            "When `False` (default), keep going after a failure and "
            "report per-item results. When `True`, abort the batch on "
            "the first failure — useful for atomic-feeling imports "
            "where partial success is worse than no success."
        ),
    )


class EntityPatchRequest(BaseModel):
    """Body for PATCH /v1/{type}/{id} — partial update of CARE-mutable
    entity-level fields. Does NOT create a new version."""

    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    tags: list[str] | None = None
    favourite: bool | None = None


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
        description="Text query for BM25, hybrid, or server-side vector search",
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
        description="Optional indexed search document kind to query",
    )
    requires_tool: list[str] | None = Field(
        default=None,
        description=(
            "For agent_skill search only: require ALL listed allowed_tools tokens"
        ),
    )
    excludes_tool: list[str] | None = Field(
        default=None,
        description=(
            "For agent_skill search only: exclude hits with ANY listed allowed_tools token"
        ),
    )
    hybrid_weights: tuple[float, float] = Field(
        default=(0.5, 0.5),
        description="(bm25_weight, vector_weight) for hybrid search, must sum to 1.0",
    )

    @model_validator(mode="after")
    def validate_tool_filters(self):
        has_tool_filter = (
            self.requires_tool is not None
            or self.excludes_tool is not None
        )
        if has_tool_filter and self.entity_type != "agent_skill":
            raise ValueError(
                "requires_tool/excludes_tool are only supported for "
                "entity_type='agent_skill'"
            )
        return self


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
        description="Optional indexed search document kind to query",
    )
    requires_tool: list[str] | None = Field(
        default=None,
        description=(
            "For agent_skill search only: require ALL listed allowed_tools tokens"
        ),
    )
    excludes_tool: list[str] | None = Field(
        default=None,
        description=(
            "For agent_skill search only: exclude hits with ANY listed allowed_tools token"
        ),
    )
    hybrid_weights: tuple[float, float] = (0.5, 0.5)

    @model_validator(mode="after")
    def validate_batch_search(self):
        has_tool_filter = (
            self.requires_tool is not None
            or self.excludes_tool is not None
        )
        if has_tool_filter and self.entity_type != "agent_skill":
            raise ValueError(
                "requires_tool/excludes_tool are only supported for "
                "entity_type='agent_skill'"
            )
        if (
            self.query_vectors is not None
            and len(self.query_vectors) != len(self.queries)
        ):
            raise ValueError("query_vectors length must match queries length")
        return self
