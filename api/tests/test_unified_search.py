"""Tests for unified search functionality (BM25 and vector)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.requests import SearchType
from app.routers.unified_search import get_embedding_service
from app.services.search_document_service import DOCUMENT_KIND_FULL_CARD
from app.services.search_strategies.base import SearchHit
from app.services.unified_search_service import UnifiedSearchService


def _hit(
    entity_id: str = "entity-1",
    *,
    entity_type: str = "memory_card",
    name: str = "Result",
    score: float = 1.0,
    tags: list[str] | None = None,
    when_to_use: str | None = None,
    content: dict | None = None,
) -> SearchHit:
    return SearchHit(
        entity_id=entity_id,
        entity_type=entity_type,
        name=name,
        score=score,
        channel="latest",
        version_id="version-1",
        tags=tags or [],
        when_to_use=when_to_use,
        content=content or {},
    )


class _RecordingStrategy:
    def __init__(self, hits):
        self.hits = hits
        self.requests = []

    async def search(self, request):
        self.requests.append(request)
        if callable(self.hits):
            return self.hits(request)
        return self.hits


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


class TestSearchType:
    """Tests for SearchType enum."""

    def test_search_type_values(self):
        """Test that SearchType has correct values."""
        assert SearchType.VECTOR == "vector"
        assert SearchType.BM25 == "bm25"
        assert SearchType.HYBRID == "hybrid"

    def test_search_type_string_conversion(self):
        """Test that SearchType can be converted to string."""
        assert str(SearchType.VECTOR) == "SearchType.VECTOR"
        assert SearchType.BM25.value == "bm25"


class TestUnifiedSearchServiceBM25:
    """Tests for BM25 search functionality."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def search_service(self, mock_db):
        """Create search service with mock database."""
        return UnifiedSearchService(mock_db)

    @pytest.mark.asyncio
    async def test_bm25_search_basic(self, search_service, mock_db):
        """Test basic BM25 search dispatch through the unified service."""
        strategy = _RecordingStrategy([
            _hit(
                name="Financial Analysis Pattern",
                score=0.8,
                tags=["finance", "analysis"],
                when_to_use="Use for financial documents",
            )
        ])
        search_service._strategies[SearchType.BM25] = strategy

        hits = await search_service.search(
            SearchType.BM25,
            query="financial analysis",
            top_k=10,
            entity_type="memory_card",
        )

        assert len(hits) == 1
        assert hits[0]["name"] == "Financial Analysis Pattern"
        assert hits[0]["entity_type"] == "memory_card"
        assert hits[0]["score"] == 0.8
        assert strategy.requests[0].query == "financial analysis"
        assert strategy.requests[0].top_k == 10
        assert strategy.requests[0].entity_type == "memory_card"
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_bm25_search_with_filters(self, search_service, mock_db):
        """Test BM25 search with tag and namespace filters."""
        strategy = _RecordingStrategy([_hit(name="Test Entity", score=0.5)])
        search_service._strategies[SearchType.BM25] = strategy

        hits = await search_service.search(
            SearchType.BM25,
            query="test",
            top_k=5,
            entity_type="memory_card",
            tags=["finance"],
            namespace="test-namespace",
            document_kind="full_card",
        )

        assert len(hits) == 1
        request = strategy.requests[0]
        assert request.tags == ["finance"]
        assert request.namespace == "test-namespace"
        assert request.document_kind == "full_card"
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_bm25_memory_card_uses_indexed_documents(
        self,
        search_service,
        mock_db,
    ):
        """Test real BM25 memory-card indexed-document search."""
        mock_row = {
            "entity_id": str(uuid.uuid4()),
            "entity_type": "memory_card",
            "name": "Financial Analysis Pattern",
            "score": 0.82,
            "channel": "latest",
            "version_id": str(uuid.uuid4()),
            "tags": ["finance", "analysis"],
            "when_to_use": "Use for financial documents",
            "content": {"description": "Financial Analysis Pattern"},
            "document_id": str(uuid.uuid4()),
            "document_kind": DOCUMENT_KIND_FULL_CARD,
            "snippet": "Financial Analysis Pattern",
        }
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        hits = await search_service.search(
            SearchType.BM25,
            query="financial analysis",
            top_k=5,
            entity_type="memory_card",
            tags=["finance"],
            namespace="test-namespace",
        )

        stmt, params = mock_db.execute.await_args.args
        sql = str(stmt)
        assert "entity_search_documents" in sql
        assert "esd.search_vector @@" in sql
        assert params["entity_type"] == "memory_card"
        assert params["document_kind"] == DOCUMENT_KIND_FULL_CARD
        assert params["namespace"] == "test-namespace"
        assert params["tag_0"] == '["finance"]'
        assert params["query"] == "financial analysis"
        assert params["top_k"] == 5
        assert hits[0]["name"] == "Financial Analysis Pattern"
        assert hits[0]["document_kind"] == DOCUMENT_KIND_FULL_CARD
        assert hits[0]["document_id"] == mock_row["document_id"]
        assert hits[0]["snippet"] == "Financial Analysis Pattern"

    @pytest.mark.asyncio
    async def test_batch_bm25_search(self, search_service, mock_db):
        """Test batch BM25 search with multiple queries."""
        strategy = _RecordingStrategy(
            lambda request: [_hit(entity_id=request.query or "missing", score=0.5)]
        )
        search_service._strategies[SearchType.BM25] = strategy

        results = await search_service.batch_search(
            SearchType.BM25,
            queries=["query1", "query2", "query3"],
            top_k=5,
            entity_type="memory_card",
        )

        assert len(results) == 3
        assert all(len(r) == 1 for r in results)
        assert [r[0]["entity_id"] for r in results] == ["query1", "query2", "query3"]
        assert [request.query for request in strategy.requests] == [
            "query1",
            "query2",
            "query3",
        ]
        assert all(request.top_k == 5 for request in strategy.requests)
        mock_db.execute.assert_not_called()


class TestUnifiedSearchServiceVector:
    """Tests for vector search functionality."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def search_service(self, mock_db):
        """Create search service with mock database."""
        return UnifiedSearchService(mock_db)

    @pytest.mark.asyncio
    async def test_vector_search_basic(self, search_service, mock_db):
        """Test basic vector search."""
        mock_row = {
            "entity_id": str(uuid.uuid4()),
            "entity_type": "memory_card",
            "name": "Test Entity",
            "score": 0.95,
            "channel": "latest",
            "version_id": str(uuid.uuid4()),
            "tags": ["test"],
            "when_to_use": "Test usage",
            "content": {"description": "Test content"},
            "document_id": str(uuid.uuid4()),
            "document_kind": "full_card",
            "snippet": "Test content",
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        query_vector = [0.1] * settings.vector_dimension
        hits = await search_service.search(
            SearchType.VECTOR,
            query_vector=query_vector,
            top_k=10,
            entity_type="memory_card",
        )

        assert len(hits) == 1
        assert hits[0]["name"] == "Test Entity"
        assert hits[0]["score"] == 0.95
        assert hits[0]["document_kind"] == "full_card"
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_vector_search_with_filters(self, search_service, mock_db):
        """Test vector search with tag and namespace filters."""
        mock_row = {
            "entity_id": str(uuid.uuid4()),
            "entity_type": "memory_card",
            "name": "Test",
            "score": 0.9,
            "channel": "latest",
            "version_id": str(uuid.uuid4()),
            "tags": ["finance"],
            "when_to_use": "Test",
            "content": {},
            "document_id": str(uuid.uuid4()),
            "document_kind": "full_card",
            "snippet": "Test",
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        query_vector = [0.1] * settings.vector_dimension
        hits = await search_service.search(
            SearchType.VECTOR,
            query_vector=query_vector,
            top_k=10,
            entity_type="memory_card",
            tags=["finance"],
            namespace="test-ns",
        )

        assert len(hits) == 1
        mock_db.execute.assert_called_once()
        _, params = mock_db.execute.await_args.args
        assert params["namespace"] == "test-ns"
        assert params["tag_0"] == '["finance"]'

    @pytest.mark.asyncio
    async def test_vector_search_invalid_dimension(self, search_service, mock_db):
        """Test vector search with wrong dimension."""
        query_vector = [0.1] * 100  # Wrong dimension

        with pytest.raises(ValueError, match="query_vector"):
            await search_service.search(
                SearchType.VECTOR,
                query_vector=query_vector,
                top_k=10,
                entity_type="memory_card",
            )

    @pytest.mark.asyncio
    async def test_batch_vector_search_uses_precomputed_vectors(self, search_service, mock_db):
        """Test batch vector search propagates precomputed vectors."""
        strategy = _RecordingStrategy(
            lambda request: [_hit(entity_id=request.query or "missing", score=0.9)]
        )
        search_service._strategies[SearchType.VECTOR] = strategy
        query_vectors = [
            [0.1] * settings.vector_dimension,
            [0.2] * settings.vector_dimension,
        ]

        results = await search_service.batch_search(
            SearchType.VECTOR,
            queries=["query1", "query2"],
            query_vectors=query_vectors,
            top_k=10,
            entity_type="memory_card",
        )

        assert [[hit["entity_id"] for hit in hits] for hits in results] == [
            ["query1"],
            ["query2"],
        ]
        assert [request.query_vector for request in strategy.requests] == query_vectors
        mock_db.execute.assert_not_called()


class TestUnifiedSearchAPI:
    """Tests for unified search API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_unified_search_bm25_endpoint_exists(self, client):
        """Test that unified search endpoint exists."""
        # This test verifies the endpoint exists and accepts POST
        # Actual functionality tested in integration tests
        response = client.post(
            "/v1/search/unified",
            json={
                "search_type": "bm25",
                "query": "test query",
                "top_k": 10,
                "entity_type": "memory_card",
            },
        )
        # May return 500 if DB not available, but should not return 404
        assert response.status_code != 404

    def test_unified_search_missing_query(self, client):
        """Test that BM25 search requires query."""
        response = client.post(
            "/v1/search/unified",
            json={
                "search_type": "bm25",
                "query": None,
                "top_k": 10,
                "entity_type": "memory_card",
            },
        )
        # Should return validation error
        assert response.status_code in [400, 422]

    def test_unified_search_vector_missing_vector(self, client, monkeypatch):
        """Test that vector search requires query_vector."""
        monkeypatch.setattr(settings, "enable_vector_search", True)

        async def _no_embedding_service():
            return None

        app.dependency_overrides[get_embedding_service] = _no_embedding_service
        response = client.post(
            "/v1/search/unified",
            json={
                "search_type": "vector",
                "query_vector": None,
                "top_k": 10,
                "entity_type": "memory_card",
            },
        )
        # Should return validation error
        assert response.status_code in [400, 422]

    def test_batch_search_endpoint_exists(self, client):
        """Test that batch search endpoint exists."""
        response = client.post(
            "/v1/search/batch",
            json={
                "search_type": "bm25",
                "queries": ["query1", "query2"],
                "top_k": 5,
                "entity_type": "memory_card",
            },
        )
        # May return 500 if DB not available, but should not return 404
        assert response.status_code != 404

    def test_batch_search_empty_queries(self, client):
        """Test that batch search rejects empty queries list."""
        response = client.post(
            "/v1/search/batch",
            json={
                "search_type": "bm25",
                "queries": [],
                "top_k": 5,
                "entity_type": "memory_card",
            },
        )
        # Should return validation error
        assert response.status_code in [400, 422]

    def test_batch_search_too_many_queries(self, client):
        """Test that batch search limits query count."""
        response = client.post(
            "/v1/search/batch",
            json={
                "search_type": "bm25",
                "queries": ["q"] * 100,  # Too many
                "top_k": 5,
                "entity_type": "memory_card",
            },
        )
        # Should return validation error
        assert response.status_code in [400, 422]
