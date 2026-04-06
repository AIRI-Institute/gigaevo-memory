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

    def list_agents(self, limit: int = 50, offset: int = 0, channel: str = "latest") -> list[EntityResponse]:
        """List all agents with pagination.

        Args:
            limit: Maximum number of results to return
            offset: Pagination offset
            channel: Version channel to retrieve (latest, stable, custom)

        Returns:
            List of EntityResponse objects for agents
        """
        return self._list_entities("agent", limit=limit, offset=offset, channel=channel)

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
