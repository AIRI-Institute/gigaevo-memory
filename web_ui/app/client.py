"""Memory client wrapper for Gradio web UI using gigaevo_memory client."""

import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add client/python/src to path for local gigaevo_memory import (for local dev)
# In Docker, gigaevo_memory is installed via pip, so this path won't exist
# noqa: E402 (intentional - must come before gigaevo_memory imports)
_client_src = Path(__file__).parent.parent.parent / "client" / "python" / "src"
if _client_src.exists() and str(_client_src) not in sys.path:
    sys.path.insert(0, str(_client_src))

from gigaevo_memory import MemoryClient  # noqa: E402
from gigaevo_memory.exceptions import MemoryError as GigaevoMemoryError  # noqa: E402

logger = logging.getLogger(__name__)


class MemoryClientError(Exception):
    """Custom exception for MemoryClient errors (for backward compatibility)."""
    pass


class MemoryClientWrapper:
    """Thin wrapper around gigaevo_memory.MemoryClient for web UI compatibility."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = MemoryClient(
            base_url=self.base_url,
            timeout=timeout,
        )
        logger.info(f"MemoryClient initialized with base_url={self.base_url}")

    def _handle_error(self, e: Exception, operation: str) -> None:
        """Convert gigaevo_memory exceptions to web UI friendly format."""
        if isinstance(e, GigaevoMemoryError):
            raise MemoryClientError(f"{operation}: {str(e)}")
        else:
            logger.error(f"{operation} failed: {type(e).__name__}: {e}")
            raise MemoryClientError(f"{operation} failed: {type(e).__name__}: {e}")

    def _entity_to_dict(self, entity) -> Dict:
        """Convert EntityResponse to dict format expected by UI."""
        return {
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "version_id": entity.version_id,
            "channel": entity.channel,
            "etag": entity.etag,
            "meta": entity.meta,
            "content": entity.content,
        }

    # Chains
    def get_chains(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """List all chains with pagination."""
        try:
            entities = self._client.list_chains(limit=limit, offset=offset)
            return [self._entity_to_dict(e) for e in entities]
        except Exception as e:
            self._handle_error(e, "GET /v1/chains")

    def get_chain(self, chain_id: str, channel: str = "latest") -> Dict:
        """Get a specific chain by ID."""
        try:
            entity = self._client.get_chain_dict(chain_id, channel=channel)
            return {"content": entity, "entity_id": chain_id}
        except Exception as e:
            self._handle_error(e, f"GET /v1/chains/{chain_id}")

    def save_chain(self, data: dict) -> Dict:
        """Create or update a chain."""
        try:
            entity_id = data.get("entity_id")
            meta = data.get("meta", {})
            ref = self._client.save_chain(
                chain=data["content"],
                name=meta.get("name", "Unnamed"),
                tags=meta.get("tags", []),
                when_to_use=meta.get("when_to_use"),
                author=meta.get("author"),
                entity_id=entity_id,
                channel=data.get("channel", "latest"),
            )
            return {"entity_id": ref.entity_id, "version_id": ref.version_id}
        except Exception as e:
            self._handle_error(e, "SAVE chain")

    def delete_chain(self, chain_id: str) -> bool:
        """Delete a chain."""
        try:
            return self._client.delete_chain(chain_id)
        except Exception as e:
            self._handle_error(e, f"DELETE /v1/chains/{chain_id}")

    # Steps
    def get_steps(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """List all steps with pagination."""
        try:
            entities = self._client.list_steps(limit=limit, offset=offset)
            return [self._entity_to_dict(e) for e in entities]
        except Exception as e:
            self._handle_error(e, "GET /v1/steps")

    def get_step(self, step_id: str, channel: str = "latest") -> Dict:
        """Get a specific step by ID."""
        try:
            entity = self._client.get_step_dict(step_id, channel=channel)
            return {"content": entity, "entity_id": step_id}
        except Exception as e:
            self._handle_error(e, f"GET /v1/steps/{step_id}")

    def save_step(self, data: dict) -> Dict:
        """Create or update a step."""
        try:
            entity_id = data.get("entity_id")
            meta = data.get("meta", {})
            ref = self._client.save_step(
                step=data["content"],
                name=meta.get("name", "Unnamed"),
                tags=meta.get("tags", []),
                when_to_use=meta.get("when_to_use"),
                author=meta.get("author"),
                entity_id=entity_id,
                channel=data.get("channel", "latest"),
            )
            return {"entity_id": ref.entity_id, "version_id": ref.version_id}
        except Exception as e:
            self._handle_error(e, "SAVE step")

    def delete_step(self, step_id: str) -> bool:
        """Delete a step."""
        try:
            return self._client.delete_step(step_id)
        except Exception as e:
            self._handle_error(e, f"DELETE /v1/steps/{step_id}")

    # Agents
    def get_agents(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """List all agents with pagination."""
        try:
            entities = self._client.list_agents(limit=limit, offset=offset)
            return [self._entity_to_dict(e) for e in entities]
        except Exception as e:
            self._handle_error(e, "GET /v1/agents")

    def get_agent(self, agent_id: str, channel: str = "latest") -> Dict:
        """Get a specific agent by ID."""
        try:
            entity = self._client.get_agent_dict(agent_id, channel=channel)
            return {"content": entity, "entity_id": agent_id}
        except Exception as e:
            self._handle_error(e, f"GET /v1/agents/{agent_id}")

    def save_agent(self, data: dict) -> Dict:
        """Create or update an agent."""
        try:
            entity_id = data.get("entity_id")
            meta = data.get("meta", {})
            ref = self._client.save_agent(
                agent=data["content"],
                name=meta.get("name", "Unnamed"),
                tags=meta.get("tags", []),
                when_to_use=meta.get("when_to_use"),
                author=meta.get("author"),
                entity_id=entity_id,
                channel=data.get("channel", "latest"),
            )
            return {"entity_id": ref.entity_id, "version_id": ref.version_id}
        except Exception as e:
            self._handle_error(e, "SAVE agent")

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent."""
        try:
            return self._client.delete_agent(agent_id)
        except Exception as e:
            self._handle_error(e, f"DELETE /v1/agents/{agent_id}")

    # Memory Cards
    def get_memory_cards(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """List all memory cards with pagination."""
        try:
            entities = self._client.list_memory_cards(limit=limit, offset=offset)
            return [self._entity_to_dict(e) for e in entities]
        except Exception as e:
            self._handle_error(e, "GET /v1/memory-cards")

    def get_memory_card(self, memory_card_id: str, channel: str = "latest") -> Dict:
        """Get a specific memory card by ID."""
        try:
            entity = self._client.get_memory_card_dict(memory_card_id, channel=channel)
            return {"content": entity, "entity_id": memory_card_id}
        except Exception as e:
            self._handle_error(e, f"GET /v1/memory-cards/{memory_card_id}")

    def save_memory_card(self, data: dict) -> Dict:
        """Create or update a memory card."""
        try:
            entity_id = data.get("entity_id")
            meta = data.get("meta", {})
            ref = self._client.save_memory_card(
                memory_card=data["content"],
                name=meta.get("name", "Unnamed"),
                tags=meta.get("tags", []),
                when_to_use=meta.get("when_to_use"),
                author=meta.get("author"),
                entity_id=entity_id,
                channel=data.get("channel", "latest"),
            )
            return {"entity_id": ref.entity_id, "version_id": ref.version_id}
        except Exception as e:
            self._handle_error(e, "SAVE memory_card")

    def delete_memory_card(self, memory_card_id: str) -> bool:
        """Delete a memory card."""
        try:
            return self._client.delete_memory_card(memory_card_id)
        except Exception as e:
            self._handle_error(e, f"DELETE /v1/memory-cards/{memory_card_id}")

    # Search
    def search(self, q: str, entity_type: str = None, limit: int = 20, **kwargs) -> Dict:
        """Search for entities with full parameter support."""
        try:
            # Build params with all supported options
            params = {"q": q, "limit": limit}
            if entity_type:
                params["entity_type"] = entity_type
            # Support additional parameters like channel, author, namespace, sort, offset
            params.update(kwargs)

            search_resp = self._client.search(**params)
            return search_resp.model_dump()
        except Exception as e:
            self._handle_error(e, f"SEARCH q={q}")

    # Health and Maintenance
    def health_check(self) -> Dict:
        """Check API health."""
        try:
            return self._client.health_check()
        except Exception as e:
            self._handle_error(e, "HEALTH_CHECK")

    def clear_all_data(self, entity_type: Optional[str] = None) -> Dict:
        """Clear all data, optionally filtered by entity type.

        Args:
            entity_type: Optional entity type to clear (step, chain, agent, memory_card).
                         If not provided, clears all entity types.

        Returns:
            Dictionary with counts of deleted entities per type.
        """
        try:
            return self._client.clear_all(entity_type=entity_type)
        except Exception as e:
            self._handle_error(e, f"CLEAR_ALL entity_type={entity_type}")

    # Version Management
    def get_versions(self, entity_id: str, entity_type: str = "chain", limit: int = 20) -> List[Dict]:
        """List all versions of an entity."""
        try:
            versions = self._client.list_versions(entity_id, entity_type, limit)
            return [v.model_dump() for v in versions]
        except Exception as e:
            self._handle_error(e, f"GET /v1/{entity_type}s/{entity_id}/versions")

    def get_version(self, entity_id: str, version_id: str, entity_type: str = "chain") -> Dict:
        """Get a specific version with its full content."""
        try:
            version = self._client.get_version(entity_id, version_id, entity_type)
            return version.model_dump()
        except Exception as e:
            self._handle_error(e, f"GET /v1/{entity_type}s/{entity_id}/versions/{version_id}")

    def diff_versions(self, entity_id: str, from_version: str, to_version: str, entity_type: str = "chain") -> Dict:
        """Compute JSON patch between two versions."""
        try:
            diff = self._client.diff_versions(entity_id, from_version, to_version, entity_type)
            return diff.model_dump()
        except Exception as e:
            self._handle_error(e, f"GET /v1/{entity_type}s/{entity_id}/diff")

    def revert(self, entity_id: str, target_version_id: str, entity_type: str = "chain") -> Dict:
        """Revert entity to a specific version."""
        try:
            ref = self._client.revert(entity_id, target_version_id, entity_type)
            return {"entity_id": ref.entity_id, "version_id": ref.version_id}
        except Exception as e:
            self._handle_error(e, f"POST /v1/{entity_type}s/{entity_id}/revert")

    def pin_channel(self, entity_id: str, channel: str, version_id: str, entity_type: str = "chain") -> Dict:
        """Pin a channel to a specific version."""
        try:
            return self._client.pin_channel(entity_id, channel, version_id, entity_type)
        except Exception as e:
            self._handle_error(e, f"POST /v1/{entity_type}s/{entity_id}/pin")

    def promote(self, entity_id: str, from_channel: str = "latest", to_channel: str = "stable", entity_type: str = "chain") -> Dict:
        """Promote channel from one to another."""
        try:
            return self._client.promote(entity_id, from_channel, to_channel, entity_type)
        except Exception as e:
            self._handle_error(e, f"POST /v1/{entity_type}s/{entity_id}/promote")

    # Unified Search
    def unified_search(self, query: str, search_type: str = "bm25",
                       top_k: int = 20, entity_type: str = "memory_card", tags: list[str] = None,
                       namespace: str = None, channel: str = "latest", hybrid_weights: tuple = (0.5, 0.5)) -> Dict:
        """Unified search supporting BM25, vector, and hybrid search types.

        Args:
            query: Text query (for BM25 and hybrid)
            search_type: Type of search ('bm25', 'vector', or 'hybrid')
            top_k: Number of results to return
            entity_type: Type of entity to search
            tags: Optional tags filter
            namespace: Optional namespace filter
            channel: Version channel
            hybrid_weights: Tuple of (bm25_weight, vector_weight) for hybrid search

        Returns:
            Search results dictionary with 'hits' and 'total'
        """
        try:
            from gigaevo_memory import SearchType as ClientSearchType
            search_type_enum = ClientSearchType(search_type)

            results = self._client.search(
                query=query,
                search_type=search_type_enum,
                top_k=top_k,
                entity_type=entity_type,
                embedding_provider=None,  # Use server-side embedding
                hybrid_weights=hybrid_weights,
            )

            # Convert MemoryCardSpec objects to dicts
            hits = []
            for card in results:
                hits.append({
                    "entity_id": card.id,
                    "entity_type": "memory_card",
                    "name": card.description,
                    "score": 0.0,  # Score not available in MemoryCardSpec
                    "channel": channel,
                    "version_id": None,
                    "tags": card.keywords or [],
                    "when_to_use": card.explanation,
                    "content": {
                        "id": card.id,
                        "description": card.description,
                        "explanation": card.explanation,
                        "keywords": card.keywords or [],
                        "category": card.category,
                        "task_description": card.task_description,
                    },
                })

            return {
                "hits": hits,
                "total": len(hits),
                "search_type": search_type,
            }
        except Exception as e:
            self._handle_error(e, f"POST /v1/search/unified ({search_type})")

    def batch_search(self, queries: list[str], search_type: str = "bm25", top_k: int = 20,
                     entity_type: str = "memory_card", tags: list[str] = None,
                     namespace: str = None, channel: str = "latest",
                     hybrid_weights: tuple = (0.5, 0.5)) -> Dict:
        """Batch search for multiple queries.

        Args:
            queries: List of search query texts
            search_type: Type of search ('bm25', 'vector', or 'hybrid')
            top_k: Number of results per query
            entity_type: Type of entity to search
            tags: Optional tags filter
            namespace: Optional namespace filter
            channel: Version channel
            hybrid_weights: Tuple of (bm25_weight, vector_weight) for hybrid search

        Returns:
            Batch search results with 'results' list and 'total_queries'
        """
        try:
            from gigaevo_memory import SearchType as ClientSearchType
            search_type_enum = ClientSearchType(search_type)

            results = self._client.batch_search(
                queries=queries,
                search_type=search_type_enum,
                top_k=top_k,
                entity_type=entity_type,
                embedding_provider=None,  # Use server-side embedding
                hybrid_weights=hybrid_weights,
            )

            # Convert list of MemoryCardSpec lists to dicts
            batch_hits = []
            for query_results in results:
                hits = []
                for card in query_results:
                    hits.append({
                        "entity_id": card.id,
                        "entity_type": "memory_card",
                        "name": card.description,
                        "score": 0.0,
                        "channel": channel,
                        "version_id": None,
                        "tags": card.keywords or [],
                        "when_to_use": card.explanation,
                        "content": {
                            "id": card.id,
                            "description": card.description,
                            "explanation": card.explanation,
                            "keywords": card.keywords or [],
                        },
                    })
                batch_hits.append(hits)

            return {
                "results": batch_hits,
                "total_queries": len(queries),
                "search_type": search_type,
            }
        except Exception as e:
            self._handle_error(e, f"POST /v1/search/batch ({search_type})")

    def get_facets(self, namespace: str = None) -> Dict:
        """Get aggregated facet counts for UI filters."""
        try:
            facets = self._client.get_facets(namespace)
            return facets.model_dump()
        except Exception as e:
            self._handle_error(e, "GET /v1/search/facets")

    def close(self):
        """Close the HTTP client."""
        self._client.close()
        logger.info("MemoryClient closed")
