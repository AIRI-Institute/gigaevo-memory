"""Vector similarity search strategy using pgvector."""

from __future__ import annotations

from sqlalchemy import text

from ...config import settings
from ..search_document_service import DOCUMENT_KIND_FULL_CARD
from ..vector_utils import serialize_vector, validate_vector
from .base import SearchHit, SearchRequest, SearchStrategy


class VectorSearchStrategy(SearchStrategy):
    """Vector similarity search using pgvector.

    Supports cosine similarity search over entity embeddings.
    """

    async def search(self, request: SearchRequest) -> list[SearchHit]:
        """Execute vector similarity search.

        Args:
            request: Search request with query_vector

        Returns:
            List of search hits with similarity scores
        """
        if not request.query_vector:
            return []

        if request.entity_type == "memory_card":
            return await self._search_memory_card_documents(request)

        # Validate query vector
        validated_vector = validate_vector(
            request.query_vector,
            expected_dimension=settings.vector_dimension,
            label="query_vector",
        )

        # Column expressions
        version_name = "COALESCE(ev.meta_json ->> 'name', e.name)"
        version_tags = "COALESCE(ev.meta_json -> 'tags', e.tags)"
        version_when_to_use = "COALESCE(ev.meta_json ->> 'when_to_use', e.when_to_use)"

        # Build filters
        filters = [
            "e.deleted_at IS NULL",
            "e.entity_type = :entity_type",
            "ev.embedding IS NOT NULL",
            "vector_dims(ev.embedding) = :vector_dimension",
            "e.channels ? :channel",
            "(e.channels ->> :channel) = ev.version_id::text",
        ]
        params: dict[str, object] = {
            "query_vector": serialize_vector(validated_vector),
            "vector_dimension": settings.vector_dimension,
            "entity_type": request.entity_type,
            "channel": request.channel,
            "top_k": request.top_k,
        }

        if request.namespace:
            filters.append("e.namespace = :namespace")
            params["namespace"] = request.namespace

        if request.tags:
            for idx, tag in enumerate(request.tags):
                tag_param = f"tag_{idx}"
                filters.append(f"{version_tags} @> CAST(:{tag_param} AS jsonb)")
                params[tag_param] = f'["{tag}"]'

        # Build query
        stmt = text(
            f"""
            SELECT
                e.entity_id::text AS entity_id,
                e.entity_type AS entity_type,
                {version_name} AS name,
                1 - (ev.embedding <=> CAST(:query_vector AS vector)) AS score,
                :channel AS channel,
                ev.version_id::text AS version_id,
                {version_tags} AS tags,
                {version_when_to_use} AS when_to_use,
                ev.content_json AS content
            FROM entities AS e
            JOIN entity_versions AS ev
              ON ev.entity_id = e.entity_id
            WHERE {" AND ".join(filters)}
            ORDER BY ev.embedding <=> CAST(:query_vector AS vector), e.entity_id
            LIMIT :top_k
            """
        )

        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        hits = []
        for row in rows:
            content = row["content"]
            hits.append(
                SearchHit(
                    entity_id=row["entity_id"],
                    entity_type=row["entity_type"],
                    name=row["name"],
                    score=float(row["score"]),
                    channel=row["channel"],
                    version_id=row["version_id"],
                    tags=row["tags"] or [],
                    when_to_use=row["when_to_use"],
                    content=content if isinstance(content, dict) else {},
                )
            )

        return hits

    async def _search_memory_card_documents(
        self,
        request: SearchRequest,
    ) -> list[SearchHit]:
        if not request.query_vector:
            return []

        validated_vector = validate_vector(
            request.query_vector,
            expected_dimension=settings.vector_dimension,
            label="query_vector",
        )
        document_kind = request.document_kind or DOCUMENT_KIND_FULL_CARD

        filters = [
            "e.deleted_at IS NULL",
            "e.entity_type = :entity_type",
            "e.channels ? :channel",
            "(e.channels ->> :channel) = ev.version_id::text",
            "esd.document_kind = :document_kind",
            "esd.embedding IS NOT NULL",
            "vector_dims(esd.embedding) = :vector_dimension",
        ]
        params: dict[str, object] = {
            "query_vector": serialize_vector(validated_vector),
            "vector_dimension": settings.vector_dimension,
            "entity_type": request.entity_type,
            "channel": request.channel,
            "document_kind": document_kind,
            "top_k": request.top_k,
        }

        if request.namespace:
            filters.append("e.namespace = :namespace")
            params["namespace"] = request.namespace

        if request.tags:
            for idx, tag in enumerate(request.tags):
                tag_param = f"tag_{idx}"
                filters.append(
                    f"COALESCE(ev.meta_json -> 'tags', e.tags) @> CAST(:{tag_param} AS jsonb)"
                )
                params[tag_param] = f'["{tag}"]'

        stmt = text(
            f"""
            SELECT
                e.entity_id::text AS entity_id,
                e.entity_type AS entity_type,
                COALESCE(ev.meta_json ->> 'name', e.name) AS name,
                1 - (esd.embedding <=> CAST(:query_vector AS vector)) AS score,
                :channel AS channel,
                ev.version_id::text AS version_id,
                COALESCE(ev.meta_json -> 'tags', e.tags) AS tags,
                COALESCE(ev.meta_json ->> 'when_to_use', e.when_to_use) AS when_to_use,
                ev.content_json AS content,
                esd.document_id::text AS document_id,
                esd.document_kind AS document_kind,
                COALESCE(esd.meta_json ->> 'snippet', LEFT(esd.text_content, 400)) AS snippet
            FROM entities AS e
            JOIN entity_versions AS ev
              ON ev.entity_id = e.entity_id
            JOIN entity_search_documents AS esd
              ON esd.version_id = ev.version_id
            WHERE {" AND ".join(filters)}
            ORDER BY esd.embedding <=> CAST(:query_vector AS vector), e.entity_id
            LIMIT :top_k
            """
        )

        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        hits = []
        for row in rows:
            content = row["content"]
            hits.append(
                SearchHit(
                    entity_id=row["entity_id"],
                    entity_type=row["entity_type"],
                    name=row["name"],
                    score=float(row["score"]),
                    channel=row["channel"],
                    version_id=row["version_id"],
                    tags=row["tags"] or [],
                    when_to_use=row["when_to_use"],
                    content=content if isinstance(content, dict) else {},
                    document_id=row["document_id"],
                    document_kind=row["document_kind"],
                    snippet=row["snippet"],
                )
            )

        return hits

    async def batch_search(
        self, request: SearchRequest, queries: list[str]
    ) -> list[list[SearchHit]]:
        """Execute batch vector search.

        Note: This method accepts text queries that need to be embedded.
        The embedding service should be called before this method.

        Args:
            request: Base search request parameters
            queries: List of query texts

        Returns:
            List of result lists, one per query
        """
        # This method should not be called directly
        # Use batch_vector_search with pre-computed vectors instead
        raise ValueError(
            "Vector batch search requires pre-computed query vectors. "
            "Use the embedding service to generate vectors before calling this method."
        )
