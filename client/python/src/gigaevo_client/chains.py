"""Chain and Step entity operations.

Provides methods for working with CARL chains and steps, including
typed access using mmar_carl types (ReasoningChain, AnyStepDescription).
"""

from __future__ import annotations

from typing import Any

from mmar_carl import AnyStepDescription, ReasoningChain

from ._base import BaseMemoryClient
from ._compat import chain_from_content, chain_to_content, step_from_content, step_to_content
from .models import AgentSpec, EntityRef, EntityResponse


class ChainsMixin(BaseMemoryClient):
    """Mixin providing chain and step operations.

    This mixin provides methods for:
    - Retrieving chains/steps as typed CARL objects or raw dicts
    - Saving chains/steps with automatic type conversion
    - Listing and deleting chains/steps
    - Resolving agent chain references
    """

    # =========================================================================
    # Chain operations - CARL-typed methods
    # =========================================================================

    def get_chain(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> ReasoningChain:
        """Get a chain as a ``ReasoningChain``.

        Uses compatibility adapters to materialize CARL chain objects
        and validate DAG dependencies.

        Args:
            entity_id: Unique identifier for the chain
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            ReasoningChain object with typed steps
        """
        data = self._get_entity("chain", entity_id, channel, cache_ttl, force_refresh)
        return chain_from_content(data["content"])

    def get_step(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> AnyStepDescription:
        """Get a step as a typed CARL step.

        Args:
            entity_id: Unique identifier for the step
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            Typed CARL step object (LLMStepDescription, ToolStepDescription, etc.)
        """
        data = self._get_entity("step", entity_id, channel, cache_ttl, force_refresh)
        return step_from_content(data["content"])

    # =========================================================================
    # Chain operations - Raw dict methods
    # =========================================================================

    def get_chain_dict(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Get chain content as a raw dict.

        Args:
            entity_id: Unique identifier for the chain
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            Raw chain content as a dictionary
        """
        data = self._get_entity("chain", entity_id, channel, cache_ttl, force_refresh)
        return data["content"]

    def get_step_dict(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Get step content as a raw dict.

        Args:
            entity_id: Unique identifier for the step
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            Raw step content as a dictionary
        """
        data = self._get_entity("step", entity_id, channel, cache_ttl, force_refresh)
        return data["content"]

    # =========================================================================
    # Save methods
    # =========================================================================

    def save_chain(
        self,
        chain: Any,
        name: str,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        entity_id: str | None = None,
        channel: str = "latest",
        evolution_meta: dict | None = None,
    ) -> EntityRef:
        """Save a ReasoningChain (or dict) to the memory module.

        Args:
            chain: ReasoningChain object or dict with chain content
            name: Human-readable name for the chain
            tags: Optional list of tags for categorization
            when_to_use: Optional description of when to use this chain
            author: Optional author attribution
            entity_id: If provided, update existing chain; otherwise create new
            channel: Version channel to update (latest, stable, custom)
            evolution_meta: Optional evolutionary metadata

        Returns:
            EntityRef with entity_id, version_id, and channel
        """
        content = chain_to_content(chain) if isinstance(chain, ReasoningChain) else chain
        return self._save_entity(
            "chain",
            content,
            name,
            tags,
            when_to_use,
            author,
            entity_id=entity_id,
            channel=channel,
            evolution_meta=evolution_meta,
        )

    def save_step(
        self,
        step: Any,
        name: str,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        entity_id: str | None = None,
        channel: str = "latest",
        evolution_meta: dict | None = None,
    ) -> EntityRef:
        """Save a typed CARL step (or dict) to the memory module.

        Args:
            step: Typed CARL step or dict with step content
            name: Human-readable name for the step
            tags: Optional list of tags for categorization
            when_to_use: Optional description of when to use this step
            author: Optional author attribution
            entity_id: If provided, update existing step; otherwise create new
            channel: Version channel to update (latest, stable, custom)
            evolution_meta: Optional evolutionary metadata

        Returns:
            EntityRef with entity_id, version_id, and channel
        """
        if isinstance(step, AnyStepDescription):
            content = step_to_content(step)
        elif hasattr(step, "model_dump"):
            content = step.model_dump()
        else:
            content = step
        return self._save_entity(
            "step",
            content,
            name,
            tags,
            when_to_use,
            author,
            entity_id=entity_id,
            channel=channel,
            evolution_meta=evolution_meta,
        )

    # =========================================================================
    # List methods
    # =========================================================================

    def get_chain_lineage(
        self,
        entity_id: str,
        *,
        channel: str = "latest",
        version_id: str | None = None,
        max_depth: int = 10,
    ):
        """Fetch the ancestry DAG for a chain (or a specific version).

        Calls ``GET /v1/chains/{entity_id}/lineage`` and returns a
        :class:`LineageResponse` carrying the BFS-ordered ancestor
        versions (root first, then deeper layers), de-duped by
        ``version_id``. CARE's "Show lineage" library action uses this
        to render an evolution-tree visualisation.

        Args:
            entity_id: Chain entity to walk lineage for.
            channel: Start from the version pinned to this channel
                (default ``"latest"``). Ignored when ``version_id`` is
                supplied.
            version_id: Walk from a specific historical version
                instead of the channel head.
            max_depth: Cap on BFS depth (1-100). Server clamps to the
                same range. The response's ``max_depth_reached`` flag
                tells the client whether more ancestors exist beyond
                the cap.

        Returns:
            :class:`LineageResponse`.
        """
        from .models import LineageResponse

        params: dict = {"channel": channel, "max_depth": max_depth}
        if version_id is not None:
            params["version_id"] = version_id
        resp = self._http.get(f"/v1/chains/{entity_id}/lineage", params=params)
        data = self._handle_response(resp)
        return LineageResponse.model_validate(data)

    def list_chain_versions_beating(
        self,
        entity_id: str,
        *,
        channel: str = "stable",
        objective: str = "fitness_score",
        limit: int = 50,
        sort_dir: str = "desc",
    ):
        """Return chain versions that beat a baseline channel on an objective.

        Calls ``GET /v1/chains/{entity_id}/versions/beating`` — the
        "promotion candidates" view. Versions are returned strictly
        ``> baseline_value`` and sorted by ``value`` (``desc`` by
        default, so the biggest wins are first).

        Args:
            entity_id: Chain to inspect.
            channel: Baseline channel — typically ``"stable"`` (the
                channel CARE wants to promote into).
            objective: Which metric to compare. ``"fitness_score"``
                (default) reads ``evolution_meta.fitness_score`` with a
                legacy ``fitness`` fallback; any other string is looked
                up in ``evolution_meta.objectives`` (e.g. ``"accuracy"``,
                ``"latency_ms"``).
            limit: Cap on the number of winners returned (1–200).
            sort_dir: ``"asc"`` or ``"desc"`` over ``value``.

        Returns:
            :class:`DifferentialChannelView`. When the baseline channel
            isn't pinned or doesn't carry the requested objective, the
            response still resolves — ``baseline_value=None`` and
            ``winners=[]`` — so the UI can render a "no baseline" state
            instead of treating it as an error.
        """
        from .models import DifferentialChannelView

        params: dict = {
            "channel": channel,
            "objective": objective,
            "limit": limit,
            "sort_dir": sort_dir,
        }
        resp = self._http.get(
            f"/v1/chains/{entity_id}/versions/beating", params=params
        )
        data = self._handle_response(resp)
        return DifferentialChannelView.model_validate(data)

    def list_chains(
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
    ) -> list[EntityResponse]:
        """List chains with CARE library sort/filter knobs.

        Defaults (``None``) defer to the server's library defaults
        (``last_run_at desc``). Pass explicit values to override.

        Args:
            limit / offset / channel: pagination + version channel.
            sort_by: ``created_at`` | ``last_run_at`` | ``run_count`` | ``display_name``.
            sort_dir: ``asc`` | ``desc``.
            favourites_only: Restrict to ``favourite=TRUE`` rows.
            tags: AND-filter — chains whose ``tags`` array contains every
                listed token.
            q: Case-insensitive substring across display_name / name /
                description.
            namespace: Restrict to a single CARE namespace.
        """
        return self._list_entities(
            "chain",
            limit=limit,
            offset=offset,
            channel=channel,
            sort_by=sort_by,
            sort_dir=sort_dir,
            favourites_only=favourites_only,
            tags=tags,
            q=q,
            namespace=namespace,
        )

    def list_chains_paged(
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
    ) -> tuple[list[EntityResponse], str | None, bool]:
        """Cursor-paginated `list_chains`. See :meth:`_list_entities_paged`.

        Returns ``(items, next_cursor, has_more)``. Stable past 10k
        entities — use this instead of offset-based ``list_chains``
        for full-library walks.
        """
        return self._list_entities_paged(
            "chain",
            cursor=cursor,
            limit=limit,
            channel=channel,
            sort_by=sort_by,
            sort_dir=sort_dir,
            favourites_only=favourites_only,
            tags=tags,
            q=q,
            namespace=namespace,
        )

    def list_steps(self, limit: int = 50, offset: int = 0, channel: str = "latest") -> list[EntityResponse]:
        """List all steps with pagination.

        Args:
            limit: Maximum number of results to return
            offset: Pagination offset
            channel: Version channel to retrieve (latest, stable, custom)

        Returns:
            List of EntityResponse objects for steps
        """
        return self._list_entities("step", limit=limit, offset=offset, channel=channel)

    # =========================================================================
    # CARE library mutations (chains)
    # =========================================================================

    def mark_chain_favourite(self, entity_id: str, value: bool = True) -> EntityResponse:
        """Set the favourite flag on a chain without creating a new version.

        ``value=True`` stars the chain; ``value=False`` unstars it.
        """
        return self._mark_favourite("chain", entity_id, value=value)

    def record_chain_run(
        self, entity_id: str, run_id: str | None = None
    ) -> EntityResponse:
        """Bump ``run_count`` and set ``last_run_at = now()``.

        Called by CARE after every successful chain run so the library
        can sort by usage/recency. Pass ``run_id`` for forthcoming
        idempotency (currently informational).
        """
        return self._record_run("chain", entity_id, run_id=run_id)

    def update_chain_metadata(
        self,
        entity_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        favourite: bool | None = None,
    ) -> EntityResponse:
        """Partial update of CARE-mutable entity-level fields on a chain.

        Only mutates explicitly-provided fields. Use ``tags=[]`` to
        clear tags. Does NOT create a new chain version.
        """
        return self._update_metadata(
            "chain",
            entity_id,
            display_name=display_name,
            description=description,
            tags=tags,
            favourite=favourite,
        )

    # =========================================================================
    # Delete methods
    # =========================================================================

    def delete_chain(self, entity_id: str) -> bool:
        """Soft-delete a chain.

        Args:
            entity_id: Unique identifier for the chain

        Returns:
            True if deletion was successful
        """
        return self._delete_entity("chain", entity_id)

    def delete_step(self, entity_id: str) -> bool:
        """Soft-delete a step.

        Args:
            entity_id: Unique identifier for the step

        Returns:
            True if deletion was successful
        """
        return self._delete_entity("step", entity_id)

    # =========================================================================
    # Agent helpers
    # =========================================================================

    def resolve_agent_chain(self, agent_spec: AgentSpec) -> ReasoningChain:
        """Materialize an agent's chain reference into a ReasoningChain.

        This helper method resolves the chain_ref in an AgentSpec
        to fetch and return the actual chain.

        Args:
            agent_spec: Agent specification containing a chain_ref

        Returns:
            ReasoningChain object
        """
        ref = agent_spec.chain_ref
        return self.get_chain(ref.entity_id, channel=ref.channel or "latest")
