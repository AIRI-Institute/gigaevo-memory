"""Tests for search strategy routing through entity_search_documents."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.models.requests import SearchType
from app.services.search_document_service import (
    DOCUMENT_KIND_SKILL_DESCRIPTION,
    DOCUMENT_KIND_SKILL_FULL,
    DOCUMENT_KIND_SKILL_INSTRUCTIONS,
)
from app.services.search_strategies.base import SearchHit, SearchRequest
from app.services.search_strategies.bm25_strategy import BM25SearchStrategy
from app.services.search_strategies.hybrid_strategy import HybridSearchStrategy
from app.services.search_strategies.vector_strategy import VectorSearchStrategy
from app.services.unified_search_service import UnifiedSearchService


def _result(rows: list[dict]) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _indexed_row(*, document_kind: str, score: float = 0.87) -> dict:
    return {
        "entity_id": "skill-1",
        "entity_type": "agent_skill",
        "name": "pdf",
        "score": score,
        "channel": "latest",
        "version_id": "version-1",
        "tags": ["pdf"],
        "when_to_use": "Extract PDFs",
        "content": {"name": "pdf", "description": "Extract PDFs"},
        "document_id": "doc-1",
        "document_kind": document_kind,
        "snippet": "Extract PDFs",
    }


def _hit(entity_id: str, score: float = 1.0) -> SearchHit:
    return SearchHit(
        entity_id=entity_id,
        entity_type="agent_skill",
        name=entity_id,
        score=score,
        channel="latest",
        version_id="version-1",
        tags=[],
        when_to_use=None,
        content={},
    )


class TestBM25IndexedDocumentRouting:
    @pytest.mark.asyncio
    async def test_agent_skill_explicit_document_kind_uses_search_documents(self):
        db = AsyncMock()
        db.execute.return_value = _result([
            _indexed_row(document_kind=DOCUMENT_KIND_SKILL_DESCRIPTION)
        ])

        hits = await BM25SearchStrategy(db).search(
            SearchRequest(
                search_type=SearchType.BM25,
                query="extract pdf",
                top_k=3,
                entity_type="agent_skill",
                document_kind=DOCUMENT_KIND_SKILL_DESCRIPTION,
            )
        )

        stmt, params = db.execute.await_args.args
        assert "entity_search_documents" in str(stmt)
        assert params["entity_type"] == "agent_skill"
        assert params["document_kind"] == DOCUMENT_KIND_SKILL_DESCRIPTION
        assert hits[0].document_kind == DOCUMENT_KIND_SKILL_DESCRIPTION
        assert hits[0].document_id == "doc-1"
        assert hits[0].snippet == "Extract PDFs"

    @pytest.mark.asyncio
    async def test_agent_skill_defaults_to_skill_full(self):
        db = AsyncMock()
        db.execute.return_value = _result([])

        await BM25SearchStrategy(db).search(
            SearchRequest(
                search_type=SearchType.BM25,
                query="extract pdf",
                top_k=3,
                entity_type="agent_skill",
            )
        )

        _, params = db.execute.await_args.args
        assert params["document_kind"] == DOCUMENT_KIND_SKILL_FULL

    @pytest.mark.asyncio
    async def test_agent_skill_allowed_tools_filters_search_documents(self):
        db = AsyncMock()
        db.execute.return_value = _result([])

        await BM25SearchStrategy(db).search(
            SearchRequest(
                search_type=SearchType.BM25,
                query="extract pdf",
                top_k=3,
                entity_type="agent_skill",
                requires_tool=["Read", "Write"],
                excludes_tool=["Bash(python:*)"],
            )
        )

        stmt, params = db.execute.await_args.args
        sql = str(stmt)
        assert "ev.content_json -> 'allowed_tools'" in sql
        assert "jsonb_typeof" in sql
        assert params["requires_tool_0"] == '["Read"]'
        assert params["requires_tool_1"] == '["Write"]'
        assert params["excludes_tool_0"] == '["Bash(python:*)"]'

    @pytest.mark.asyncio
    async def test_non_indexed_type_keeps_entity_level_search(self):
        db = AsyncMock()
        db.execute.return_value = _result([])

        await BM25SearchStrategy(db).search(
            SearchRequest(
                search_type=SearchType.BM25,
                query="chain",
                top_k=3,
                entity_type="chain",
                document_kind=DOCUMENT_KIND_SKILL_DESCRIPTION,
            )
        )

        (stmt,) = db.execute.await_args.args
        assert "entity_search_documents" not in str(stmt)


class TestVectorIndexedDocumentRouting:
    @pytest.mark.asyncio
    async def test_agent_skill_explicit_document_kind_uses_search_documents(self):
        db = AsyncMock()
        db.execute.return_value = _result([
            _indexed_row(document_kind=DOCUMENT_KIND_SKILL_INSTRUCTIONS, score=0.96)
        ])

        hits = await VectorSearchStrategy(db).search(
            SearchRequest(
                search_type=SearchType.VECTOR,
                query_vector=[0.1] * settings.vector_dimension,
                top_k=3,
                entity_type="agent_skill",
                document_kind=DOCUMENT_KIND_SKILL_INSTRUCTIONS,
            )
        )

        stmt, params = db.execute.await_args.args
        sql = str(stmt)
        assert "entity_search_documents" in sql
        assert "esd.embedding <=>" in sql
        assert params["entity_type"] == "agent_skill"
        assert params["document_kind"] == DOCUMENT_KIND_SKILL_INSTRUCTIONS
        assert hits[0].document_kind == DOCUMENT_KIND_SKILL_INSTRUCTIONS

    @pytest.mark.asyncio
    async def test_agent_skill_defaults_to_skill_instructions(self):
        db = AsyncMock()
        db.execute.return_value = _result([])

        await VectorSearchStrategy(db).search(
            SearchRequest(
                search_type=SearchType.VECTOR,
                query_vector=[0.1] * settings.vector_dimension,
                top_k=3,
                entity_type="agent_skill",
            )
        )

        _, params = db.execute.await_args.args
        assert params["document_kind"] == DOCUMENT_KIND_SKILL_INSTRUCTIONS

    @pytest.mark.asyncio
    async def test_agent_skill_allowed_tools_filters_search_documents(self):
        db = AsyncMock()
        db.execute.return_value = _result([])

        await VectorSearchStrategy(db).search(
            SearchRequest(
                search_type=SearchType.VECTOR,
                query_vector=[0.1] * settings.vector_dimension,
                top_k=3,
                entity_type="agent_skill",
                requires_tool=["Read"],
                excludes_tool=["Bash(python:*)"],
            )
        )

        stmt, params = db.execute.await_args.args
        sql = str(stmt)
        assert "entity_search_documents" in sql
        assert "esd.embedding <=>" in sql
        assert "ev.content_json -> 'allowed_tools'" in sql
        assert params["requires_tool_0"] == '["Read"]'
        assert params["excludes_tool_0"] == '["Bash(python:*)"]'

    @pytest.mark.asyncio
    async def test_service_embeds_query_before_agent_skill_document_search(self):
        db = AsyncMock()
        db.execute.return_value = _result([
            _indexed_row(document_kind=DOCUMENT_KIND_SKILL_INSTRUCTIONS, score=0.96)
        ])
        embedding_service = MagicMock()
        embedding_service.embed_query = AsyncMock(
            return_value=[0.1] * settings.vector_dimension
        )

        hits = await UnifiedSearchService(
            db,
            embedding_service=embedding_service,
        ).search(
            SearchType.VECTOR,
            query="extract pdf",
            top_k=3,
            entity_type="agent_skill",
        )

        embedding_service.embed_query.assert_awaited_once_with("extract pdf")
        stmt, params = db.execute.await_args.args
        sql = str(stmt)
        assert "entity_search_documents" in sql
        assert "esd.embedding <=>" in sql
        assert params["entity_type"] == "agent_skill"
        assert params["document_kind"] == DOCUMENT_KIND_SKILL_INSTRUCTIONS
        assert hits[0]["document_kind"] == DOCUMENT_KIND_SKILL_INSTRUCTIONS
        assert hits[0]["document_id"] == "doc-1"


class TestIndexedDocumentToolFilterPropagation:
    @pytest.mark.asyncio
    async def test_hybrid_passes_tool_filters_to_bm25_and_vector(self):
        strategy = HybridSearchStrategy(AsyncMock())
        strategy._bm25_strategy.search = AsyncMock(return_value=[])
        strategy._vector_strategy.search = AsyncMock(return_value=[])

        await strategy.search(
            SearchRequest(
                search_type=SearchType.HYBRID,
                query="extract pdf",
                query_vector=[0.1] * settings.vector_dimension,
                top_k=3,
                entity_type="agent_skill",
                requires_tool=["Read"],
                excludes_tool=["Bash(python:*)"],
            )
        )

        bm25_request = strategy._bm25_strategy.search.await_args.args[0]
        vector_request = strategy._vector_strategy.search.await_args.args[0]
        assert bm25_request.requires_tool == ["Read"]
        assert bm25_request.excludes_tool == ["Bash(python:*)"]
        assert vector_request.requires_tool == ["Read"]
        assert vector_request.excludes_tool == ["Bash(python:*)"]

    @pytest.mark.asyncio
    async def test_hybrid_search_runs_bm25_then_vector_without_overlap(self):
        strategy = HybridSearchStrategy(AsyncMock())
        events: list[str] = []

        async def bm25_search(_request):
            events.append("bm25-start")
            await asyncio.sleep(0)
            events.append("bm25-end")
            return [_hit("bm25-only")]

        async def vector_search(_request):
            events.append("vector-start")
            await asyncio.sleep(0)
            events.append("vector-end")
            return [_hit("vector-only")]

        strategy._bm25_strategy.search = bm25_search
        strategy._vector_strategy.search = vector_search

        await strategy.search(
            SearchRequest(
                search_type=SearchType.HYBRID,
                query="extract pdf",
                query_vector=[0.1] * settings.vector_dimension,
                top_k=3,
                entity_type="agent_skill",
            )
        )

        assert events == [
            "bm25-start",
            "bm25-end",
            "vector-start",
            "vector-end",
        ]

    @pytest.mark.asyncio
    async def test_batch_search_passes_tool_filters_to_each_query(self):
        service = UnifiedSearchService(AsyncMock())
        seen_requests = []

        class FakeStrategy:
            async def search(self, request):
                seen_requests.append(request)
                return []

        service._strategies[SearchType.BM25] = FakeStrategy()

        await service.batch_search(
            SearchType.BM25,
            queries=["extract pdf", "read docs"],
            top_k=3,
            entity_type="agent_skill",
            requires_tool=["Read"],
            excludes_tool=["Bash(python:*)"],
        )

        assert len(seen_requests) == 2
        assert all(request.requires_tool == ["Read"] for request in seen_requests)
        assert all(
            request.excludes_tool == ["Bash(python:*)"]
            for request in seen_requests
        )

    @pytest.mark.asyncio
    async def test_batch_search_runs_retrieval_serially_and_preserves_order(self):
        service = UnifiedSearchService(AsyncMock())
        in_flight = 0
        max_in_flight = 0
        seen_queries: list[str | None] = []

        class FakeStrategy:
            async def search(self, request):
                nonlocal in_flight, max_in_flight
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                seen_queries.append(request.query)
                await asyncio.sleep(0)
                in_flight -= 1
                return [_hit(request.query or "missing")]

        service._strategies[SearchType.BM25] = FakeStrategy()

        results = await service.batch_search(
            SearchType.BM25,
            queries=["query-1", "query-2", "query-3"],
            top_k=3,
            entity_type="agent_skill",
        )

        assert max_in_flight == 1
        assert seen_queries == ["query-1", "query-2", "query-3"]
        assert [[hit["entity_id"] for hit in hits] for hits in results] == [
            ["query-1"],
            ["query-2"],
            ["query-3"],
        ]

    @pytest.mark.asyncio
    async def test_batch_search_rejects_vector_count_mismatch_before_retrieval(self):
        service = UnifiedSearchService(AsyncMock())
        seen_requests = []

        class FakeStrategy:
            async def search(self, request):
                seen_requests.append(request)
                return []

        service._strategies[SearchType.BM25] = FakeStrategy()

        with pytest.raises(ValueError, match="query_vectors length"):
            await service.batch_search(
                SearchType.BM25,
                queries=["query-1", "query-2"],
                query_vectors=[[0.1] * settings.vector_dimension],
                entity_type="agent_skill",
            )

        assert seen_requests == []

    @pytest.mark.asyncio
    async def test_batch_search_rejects_embedding_count_mismatch_before_retrieval(self):
        embedding_service = MagicMock()
        embedding_service.embed_batch = AsyncMock(
            return_value=[[0.1] * settings.vector_dimension]
        )
        service = UnifiedSearchService(
            AsyncMock(),
            embedding_service=embedding_service,
        )
        seen_requests = []

        class FakeStrategy:
            async def search(self, request):
                seen_requests.append(request)
                return []

        service._strategies[SearchType.VECTOR] = FakeStrategy()

        with pytest.raises(ValueError, match="query_vectors length"):
            await service.batch_search(
                SearchType.VECTOR,
                queries=["query-1", "query-2"],
                entity_type="agent_skill",
            )

        embedding_service.embed_batch.assert_awaited_once_with(
            ["query-1", "query-2"]
        )
        assert seen_requests == []
