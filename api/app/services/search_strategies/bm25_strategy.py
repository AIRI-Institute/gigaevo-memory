"""BM25 full-text search strategy using PostgreSQL tsvector."""

from __future__ import annotations

from sqlalchemy import String, cast, func, literal_column, select, text

from ...db.models import Entity
from ..search_document_service import DOCUMENT_KIND_FULL_CARD
from .base import SearchHit, SearchRequest, SearchStrategy


class BM25SearchStrategy(SearchStrategy):
    """BM25 full-text search using PostgreSQL tsvector.

    Uses websearch_to_tsquery for natural query syntax support
    (phrases with quotes, OR with |, AND with space).
    """

    async def search(self, request: SearchRequest) -> list[SearchHit]:
        """Execute BM25 search.

        Args:
            request: Search request with query text

        Returns:
            List of search hits with BM25 scores
        """
        if not request.query:
            return []

        if request.entity_type == "memory_card":
            return await self._search_memory_card_documents(request)

        # Build BM25 query using websearch_to_tsquery
        # This supports phrases with quotes, OR with |, AND with space
        tsquery = func.websearch_to_tsquery("english", request.query)

        # Calculate rank with normalization
        rank_expr = func.ts_rank_cd(
            Entity.search_vector,
            tsquery,
            32,  # Normalization: divide by document length + 1
        ).label("score")

        # Build base conditions
        conditions = [
            Entity.deleted_at.is_(None),
            Entity.entity_type == request.entity_type,
            Entity.search_vector.op("@@")(tsquery),
        ]

        # Add namespace filter
        if request.namespace:
            conditions.append(Entity.namespace == request.namespace)

        # Add tags filter
        if request.tags:
            for tag in request.tags:
                conditions.append(Entity.tags.contains([tag]))

        # Build query
        stmt = (
            select(
                cast(Entity.entity_id, String).label("entity_id"),
                Entity.entity_type.label("entity_type"),
                Entity.name.label("name"),
                rank_expr,
                literal_column("'latest'").label("channel"),
                cast(Entity.channels["latest"].astext, String).label("version_id"),
                Entity.tags.label("tags"),
                Entity.when_to_use.label("when_to_use"),
            )
            .select_from(Entity)
            .where(*conditions)
            .order_by(rank_expr.desc())
            .limit(request.top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.mappings().all()

        hits = []
        for row in rows:
            # Build content dict
            content = {
                "id": row["entity_id"],
                "description": row["name"],
                "explanation": row["when_to_use"] or "",
                "keywords": list(row["tags"]) if row["tags"] else [],
            }

            hits.append(
                SearchHit(
                    entity_id=row["entity_id"],
                    entity_type=row["entity_type"],
                    name=row["name"],
                    score=float(row["score"]) if row["score"] else 0.0,
                    channel=row["channel"],
                    version_id=row["version_id"],
                    tags=list(row["tags"]) if row["tags"] else [],
                    when_to_use=row["when_to_use"],
                    content=content,
                )
            )

        return hits

    async def _search_memory_card_documents(
        self,
        request: SearchRequest,
    ) -> list[SearchHit]:
        document_kind = request.document_kind or DOCUMENT_KIND_FULL_CARD
        filters = [
            "e.deleted_at IS NULL",
            "e.entity_type = :entity_type",
            "e.channels ? :channel",
            "(e.channels ->> :channel) = ev.version_id::text",
            "esd.document_kind = :document_kind",
            "esd.search_vector @@ websearch_to_tsquery('english', :query)",
        ]
        params: dict[str, object] = {
            "entity_type": request.entity_type,
            "channel": request.channel,
            "document_kind": document_kind,
            "query": request.query,
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
                ts_rank_cd(
                    esd.search_vector,
                    websearch_to_tsquery('english', :query),
                    32
                ) AS score,
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
            ORDER BY score DESC, e.entity_id
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
                    score=float(row["score"]) if row["score"] else 0.0,
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
        """Execute batch BM25 search.

        Args:
            request: Base search request parameters
            queries: List of query texts

        Returns:
            List of result lists, one per query
        """
        results = []
        for query in queries:
            search_request = SearchRequest(
                search_type=request.search_type,
                query=query,
                top_k=request.top_k,
                entity_type=request.entity_type,
                tags=request.tags,
                namespace=request.namespace,
                channel=request.channel,
                document_kind=request.document_kind,
                hybrid_weights=request.hybrid_weights,
            )
            hits = await self.search(search_request)
            results.append(hits)
        return results
