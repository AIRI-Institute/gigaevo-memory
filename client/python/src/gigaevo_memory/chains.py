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

    def list_chains(self, limit: int = 50, offset: int = 0, channel: str = "latest") -> list[EntityResponse]:
        """List all chains with pagination.

        Args:
            limit: Maximum number of results to return
            offset: Pagination offset
            channel: Version channel to retrieve (latest, stable, custom)

        Returns:
            List of EntityResponse objects for chains
        """
        return self._list_entities("chain", limit=limit, offset=offset, channel=channel)

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
