"""AgentSkill entity operations.

Provides methods for persisting and retrieving AgentSkill specifications
in GigaEvo Memory. An AgentSkill mirrors the on-disk structure of a
portable SKILL.md folder (manifest + instructions + allowed-tools),
persisted so CARE-generated chains can reference the skill by stable
entity_id and MAGE's capability lookup can search SKILL.md content.
"""

from __future__ import annotations

from typing import Any

from ._base import BaseMemoryClient
from .models import AgentSkillSpec, EntityRef, EntityResponse


def _extract_skill_spec(resolved: Any) -> AgentSkillSpec:
    """Coerce a duck-typed input into an :class:`AgentSkillSpec`.

    Accepts any of:
      * A CARL ``ResolvedSkill`` (or any object exposing the same
        attribute surface: ``manifest`` with ``name`` / ``description`` /
        ``instructions`` / ``get_allowed_tools()`` / ``metadata`` /
        ``compatibility``, plus top-level ``sha256`` / ``source_uri`` /
        ``tarball_url`` / ``tarball_sha256``).
      * A plain dict matching :class:`AgentSkillSpec`.
      * An :class:`AgentSkillSpec` (pass-through).

    Kept duck-typed so callers don't take a hard ``mmar_carl`` import.
    """
    if isinstance(resolved, AgentSkillSpec):
        return resolved
    if isinstance(resolved, dict):
        return AgentSkillSpec.model_validate(resolved)

    manifest = getattr(resolved, "manifest", None)
    if manifest is None:
        raise ValueError(
            "ingest_skill_from_carl: input must be an AgentSkillSpec, a dict, "
            "or an object exposing a `manifest` attribute (CARL ResolvedSkill)."
        )

    name = getattr(manifest, "name", None) or ""
    description = getattr(manifest, "description", None) or ""

    # Instructions: prefer the canonical attribute, fall back to common aliases.
    instructions = (
        getattr(manifest, "instructions", None)
        or getattr(manifest, "body", None)
        or ""
    )

    # Allowed tools: prefer the parsed-list method, fall back to the raw attr.
    get_allowed = getattr(manifest, "get_allowed_tools", None)
    if callable(get_allowed):
        allowed_tools = [str(t) for t in (get_allowed() or [])]
    else:
        allowed_tools = [str(t) for t in (getattr(manifest, "allowed_tools", None) or [])]

    manifest_meta = dict(getattr(manifest, "metadata", {}) or {})
    compatibility = getattr(manifest, "compatibility", None)

    # SHA and URI live on the ResolvedSkill, not on the manifest.
    sha = getattr(resolved, "sha256", None) or getattr(resolved, "skill_md_sha256", None)
    if not sha:
        raise ValueError(
            "ingest_skill_from_carl: input is missing `sha256` (or `skill_md_sha256`). "
            "Compute it from SKILL.md bytes before calling."
        )

    uri = getattr(resolved, "source_uri", None) or getattr(resolved, "uri", None)
    if not uri:
        raise ValueError(
            "ingest_skill_from_carl: input is missing `source_uri` (or `uri`)."
        )

    # Tags can live on the manifest object or inside its metadata dict;
    # support both, keeping the union (de-duplicated, order-preserving).
    raw_tags = list(getattr(manifest, "tags", None) or [])
    if not raw_tags and isinstance(manifest_meta.get("tags"), list):
        raw_tags = list(manifest_meta["tags"])
    seen: set[str] = set()
    tags = [t for t in raw_tags if not (t in seen or seen.add(t))]

    return AgentSkillSpec(
        name=name,
        description=description,
        uri=uri,
        sha256=sha,
        manifest=manifest_meta,
        instructions=instructions,
        allowed_tools=allowed_tools,
        tags=tags,
        compatibility=compatibility,
        tarball_url=getattr(resolved, "tarball_url", None),
        tarball_sha256=getattr(resolved, "tarball_sha256", None),
    )


class AgentSkillsMixin(BaseMemoryClient):
    """Mixin providing agent_skill CRUD operations.

    All methods follow the existing entity-mixin contract: typed
    accessors return Pydantic models; ``*_dict`` variants return raw
    dicts; ``save_*`` accepts either a typed model or a dict and returns
    an ``EntityRef``.
    """

    # =========================================================================
    # AgentSkill operations - Typed methods
    # =========================================================================

    def get_agent_skill(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> AgentSkillSpec:
        """Get an agent_skill specification.

        Args:
            entity_id: Unique identifier for the agent_skill
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            AgentSkillSpec object
        """
        data = self._get_entity(
            "agent_skill", entity_id, channel, cache_ttl, force_refresh
        )
        return AgentSkillSpec.model_validate(data["content"])

    # =========================================================================
    # AgentSkill operations - Raw dict methods
    # =========================================================================

    def get_agent_skill_dict(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Get agent_skill content as a raw dict.

        Returns:
            Raw agent_skill content as a dictionary
        """
        data = self._get_entity(
            "agent_skill", entity_id, channel, cache_ttl, force_refresh
        )
        return data["content"]

    # =========================================================================
    # Save methods
    # =========================================================================

    def ingest_skill_from_carl(
        self,
        resolved_skill: Any,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        namespace: str | None = None,
        entity_id: str | None = None,
        channel: str = "latest",
    ) -> EntityRef:
        """Persist a CARL ``ResolvedSkill`` as an ``agent_skill`` entity.

        Reads the manifest / instructions / allowed_tools / sha256 / uri
        from the input (see :func:`_extract_skill_spec` for the supported
        shapes), builds an :class:`AgentSkillSpec`, and calls
        :meth:`save_agent_skill`.

        Idempotent re-ingestion: when ``entity_id`` is supplied, this
        creates a new version of an existing skill entity (the SHA in
        the content payload tracks SKILL.md identity per-version).
        Without ``entity_id``, a new entity is created.

        Args:
            resolved_skill: A CARL ``ResolvedSkill``, an
                :class:`AgentSkillSpec`, or a dict matching the spec.
            name: Override for the entity ``meta.name``. Defaults to
                the skill's own name from its manifest.
            tags: Override for ``meta.tags``. Defaults to the tags
                extracted from the manifest.
            when_to_use, author, namespace, channel: passed to
                :meth:`save_agent_skill` unchanged.
            entity_id: If supplied, upserts onto an existing skill
                entity (creates a new version); otherwise creates new.

        Returns:
            An :class:`EntityRef` to the persisted version.
        """
        spec = _extract_skill_spec(resolved_skill)
        return self.save_agent_skill(
            spec,
            name=name or spec.name,
            tags=tags if tags is not None else (list(spec.tags) or None),
            when_to_use=when_to_use,
            author=author,
            namespace=namespace,
            entity_id=entity_id,
            channel=channel,
        )

    def save_agent_skill(
        self,
        skill: AgentSkillSpec | dict,
        name: str,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        namespace: str | None = None,
        entity_id: str | None = None,
        channel: str = "latest",
    ) -> EntityRef:
        """Save an agent_skill specification.

        Args:
            skill: AgentSkillSpec object or dict with skill content
            name: Human-readable name for the skill (typically matches
                ``skill.name`` from the SKILL.md frontmatter)
            tags: Optional list of tags for categorization
            when_to_use: Optional description of when to use this skill
            author: Optional author attribution
            namespace: Optional logical memory namespace
            entity_id: If provided, update existing skill; otherwise create new
            channel: Version channel to update (latest, stable, custom)

        Returns:
            EntityRef with entity_id, version_id, and channel
        """
        content = (
            skill.model_dump(mode="json") if isinstance(skill, AgentSkillSpec) else skill
        )
        return self._save_entity(
            "agent_skill",
            content,
            name,
            tags,
            when_to_use,
            author,
            namespace=namespace,
            entity_id=entity_id,
            channel=channel,
        )

    # =========================================================================
    # List methods
    # =========================================================================

    def list_agent_skills(
        self,
        limit: int = 50,
        offset: int = 0,
        channel: str = "latest",
        *,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        favourites_only: bool | None = None,
        tags: list[str] | None = None,
        q: str | None = None,
        namespace: str | None = None,
        requires_tools: list[str] | None = None,
        excludes_tools: list[str] | None = None,
    ) -> list[EntityResponse]:
        """List agent_skills with CARE catalogue sort/filter knobs.

        Defaults (``None``) defer to the server's library defaults
        (``last_run_at desc``). Pass explicit values to override.

        Args:
            limit / offset / channel: pagination + version channel.
            sort_by: ``created_at`` | ``last_run_at`` | ``run_count`` | ``display_name``.
            sort_dir: ``asc`` | ``desc``.
            favourites_only: Restrict to ``favourite=TRUE`` rows.
            tags: AND-filter — skills whose ``tags`` array contains every
                listed token.
            q: Case-insensitive substring across display_name / name /
                description.
            namespace: Restrict to a single CARE namespace.
            requires_tools: AND-filter — only return skills whose
                ``allowed_tools`` array contains every listed token
                (e.g. ``["Read", "Write"]`` for "skills that need both
                Read and Write").
            excludes_tools: Drop skills that mention ANY of the listed
                tokens in ``allowed_tools`` (e.g. ``["Bash"]`` for
                "skills that don't require Bash").
        """
        # `_list_entities` doesn't know about `requires_tool` /
        # `excludes_tool`; pass them via the kwargs dict it forwards.
        params_extra: dict[str, list[str]] = {}
        if requires_tools:
            params_extra["requires_tool"] = list(requires_tools)
        if excludes_tools:
            params_extra["excludes_tool"] = list(excludes_tools)

        return self._list_entities(
            "agent_skill",
            limit=limit,
            offset=offset,
            channel=channel,
            sort_by=sort_by,
            sort_dir=sort_dir,
            favourites_only=favourites_only,
            tags=tags,
            q=q,
            namespace=namespace,
            extra_params=params_extra,
        )

    def list_agent_skills_paged(
        self,
        cursor: str | None = None,
        limit: int = 50,
        channel: str = "latest",
        *,
        sort_by: str | None = None,
        sort_dir: str | None = None,
        favourites_only: bool | None = None,
        tags: list[str] | None = None,
        q: str | None = None,
        namespace: str | None = None,
        requires_tools: list[str] | None = None,
        excludes_tools: list[str] | None = None,
    ) -> tuple[list[EntityResponse], str | None, bool]:
        """Cursor-paginated `list_agent_skills`. See
        :meth:`_list_entities_paged`.

        Returns ``(items, next_cursor, has_more)``. When `requires_tools`
        / `excludes_tools` are set, the server applies the post-filter
        and returns ``has_more=False`` + ``next_cursor=None`` — fall
        back to offset-based pagination for tool-filtered walks.
        """
        extra: dict[str, list[str]] = {}
        if requires_tools:
            extra["requires_tool"] = list(requires_tools)
        if excludes_tools:
            extra["excludes_tool"] = list(excludes_tools)
        return self._list_entities_paged(
            "agent_skill",
            cursor=cursor,
            limit=limit,
            channel=channel,
            sort_by=sort_by,
            sort_dir=sort_dir,
            favourites_only=favourites_only,
            tags=tags,
            q=q,
            namespace=namespace,
            extra_params=extra,
        )

    # =========================================================================
    # CARE library mutations (agent_skills)
    # =========================================================================

    def mark_agent_skill_favourite(
        self, entity_id: str, value: bool = True
    ) -> EntityResponse:
        """Set the favourite flag on an agent_skill without creating a new version."""
        return self._mark_favourite("agent_skill", entity_id, value=value)

    def record_agent_skill_run(
        self, entity_id: str, run_id: str | None = None
    ) -> EntityResponse:
        """Bump ``run_count`` and set ``last_run_at = now()`` on an agent_skill."""
        return self._record_run("agent_skill", entity_id, run_id=run_id)

    def update_agent_skill_metadata(
        self,
        entity_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        favourite: bool | None = None,
    ) -> EntityResponse:
        """Partial update of CARE-mutable entity-level fields on an agent_skill.

        Only mutates explicitly-provided fields. Use ``tags=[]`` to
        clear tags. Does NOT create a new version.
        """
        return self._update_metadata(
            "agent_skill",
            entity_id,
            display_name=display_name,
            description=description,
            tags=tags,
            favourite=favourite,
        )

    # =========================================================================
    # Delete methods
    # =========================================================================

    def delete_agent_skill(self, entity_id: str) -> bool:
        """Soft-delete an agent_skill.

        Returns:
            True if deletion was successful
        """
        return self._delete_entity("agent_skill", entity_id)
