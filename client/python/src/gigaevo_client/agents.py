"""Agent entity operations.

Provides methods for working with agent specifications.
"""

from __future__ import annotations

from ._base import BaseMemoryClient
from .models import AgentSpec, EntityRef, EntityResponse


class AgentsMixin(BaseMemoryClient):
    """Mixin providing agent operations.

    This mixin provides methods for:
    - Retrieving agents as AgentSpec or raw dicts
    - Saving agents with automatic type conversion
    - Listing and deleting agents
    """

    # =========================================================================
    # Agent operations - Typed methods
    # =========================================================================

    def get_agent(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> AgentSpec:
        """Get an agent specification.

        Args:
            entity_id: Unique identifier for the agent
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            AgentSpec object
        """
        data = self._get_entity("agent", entity_id, channel, cache_ttl, force_refresh)
        return AgentSpec.model_validate(data["content"])

    # =========================================================================
    # Agent operations - Raw dict methods
    # =========================================================================

    def get_agent_dict(
        self,
        entity_id: str,
        channel: str = "latest",
        cache_ttl: int | None = None,
        force_refresh: bool = False,
    ) -> dict:
        """Get agent content as a raw dict.

        Args:
            entity_id: Unique identifier for the agent
            channel: Version channel to retrieve (latest, stable, custom)
            cache_ttl: Override default cache TTL for this request
            force_refresh: Bypass cache and fetch from server

        Returns:
            Raw agent content as a dictionary
        """
        data = self._get_entity("agent", entity_id, channel, cache_ttl, force_refresh)
        return data["content"]

    # =========================================================================
    # Save methods
    # =========================================================================

    def save_agent(
        self,
        agent: AgentSpec | dict,
        name: str,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        entity_id: str | None = None,
        channel: str = "latest",
    ) -> EntityRef:
        """Save an agent specification.

        Args:
            agent: AgentSpec object or dict with agent content
            name: Human-readable name for the agent
            tags: Optional list of tags for categorization
            when_to_use: Optional description of when to use this agent
            author: Optional author attribution
            entity_id: If provided, update existing agent; otherwise create new
            channel: Version channel to update (latest, stable, custom)

        Returns:
            EntityRef with entity_id, version_id, and channel
        """
        content = agent.model_dump(mode="json") if isinstance(agent, AgentSpec) else agent
        return self._save_entity(
            "agent",
            content,
            name,
            tags,
            when_to_use,
            author,
            entity_id=entity_id,
            channel=channel,
        )

    # =========================================================================
    # List methods
    # =========================================================================

    def list_agents(
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
        """List agents with CARE library sort/filter knobs.

        Defaults (``sort_by=None``) defer to the server's library
        defaults (``last_run_at desc``). Pass explicit values to
        override.

        Args:
            limit / offset / channel: pagination + version channel.
            sort_by: ``created_at`` | ``last_run_at`` | ``run_count`` | ``display_name``.
            sort_dir: ``asc`` | ``desc``.
            favourites_only: Restrict to ``favourite=TRUE`` rows.
            tags: AND-filter — entities whose ``tags`` array contains
                every listed token.
            q: Case-insensitive substring across display_name / name /
                description.
            namespace: Restrict to a single CARE namespace.
        """
        return self._list_entities(
            "agent",
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

    def list_agents_paged(
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
        """Cursor-paginated `list_agents`. See :meth:`_list_entities_paged`.

        Returns ``(items, next_cursor, has_more)`` — stable past 10k
        entities. Pass the returned ``next_cursor`` back as ``cursor=``
        to fetch the next page.
        """
        return self._list_entities_paged(
            "agent",
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

    # =========================================================================
    # CARE library mutations
    # =========================================================================

    def mark_favourite(self, entity_id: str, value: bool = True) -> EntityResponse:
        """Set the favourite flag on an agent without creating a new version.

        ``value=True`` stars the agent; ``value=False`` unstars it.
        """
        return self._mark_favourite("agent", entity_id, value=value)

    def record_run(
        self, entity_id: str, run_id: str | None = None
    ) -> EntityResponse:
        """Bump ``run_count`` and set ``last_run_at = now()``.

        Called by CARE after every successful agent run so the library
        can sort by usage/recency. Pass ``run_id`` for forthcoming
        idempotency (currently informational).
        """
        return self._record_run("agent", entity_id, run_id=run_id)

    def update_metadata(
        self,
        entity_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        favourite: bool | None = None,
    ) -> EntityResponse:
        """Partial update of CARE-mutable entity-level fields.

        Only mutates explicitly-provided fields. Use ``tags=[]`` to
        clear tags. Does NOT create a new version.
        """
        return self._update_metadata(
            "agent",
            entity_id,
            display_name=display_name,
            description=description,
            tags=tags,
            favourite=favourite,
        )

    # =========================================================================
    # Delete methods
    # =========================================================================

    def delete_agent(self, entity_id: str) -> bool:
        """Soft-delete an agent.

        Args:
            entity_id: Unique identifier for the agent

        Returns:
            True if deletion was successful
        """
        return self._delete_entity("agent", entity_id)
