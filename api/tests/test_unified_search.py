"""Tests for unified search functionality (BM25 and vector)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services.unified_search_service import SearchType, UnifiedSearchService


class TestSearchType:
    """Tests for SearchType enum."""

    def test_search_type_values(self):
        """Test that SearchType has correct values."""
        assert SearchType.VECTOR == "vector"
        assert SearchType.BM25 == "bm25"

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
        """Test basic BM25 search."""
        # Mock database response
        mock_entity = MagicMock()
        mock_entity.entity_id = uuid.uuid4()
        mock_entity.entity_type = "memory_card"
        mock_entity.name = "Financial Analysis Pattern"
        mock_entity.when_to_use = "Use for financial documents"
        mock_entity.tags = ["finance", "analysis"]
        mock_entity.channels = {"latest": uuid.uuid4()}
        mock_entity.deleted_at = None

        mock_result = MagicMock()
        mock_result.all.return_value = [(mock_entity, 0.8)]

        mock_db.execute.return_value = mock_result

        # Execute search
        hits = await search_service.bm25_search(
            query="financial analysis",
            top_k=10,
            entity_type="memory_card",
        )

        # Verify
        assert len(hits) == 1
        assert hits[0]["name"] == "Financial Analysis Pattern"
        assert hits[0]["entity_type"] == "memory_card"
        assert hits[0]["score"] == 0.8
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_bm25_search_with_filters(self, search_service, mock_db):
        """Test BM25 search with tag and namespace filters."""
        mock_entity = MagicMock()
        mock_entity.entity_id = uuid.uuid4()
        mock_entity.entity_type = "memory_card"
        mock_entity.name = "Test Entity"
        mock_entity.when_to_use = "Test usage"
        mock_entity.tags = ["finance"]
        mock_entity.channels = {"latest": uuid.uuid4()}
        mock_entity.deleted_at = None

        mock_result = MagicMock()
        mock_result.all.return_value = [(mock_entity, 0.5)]

        mock_db.execute.return_value = mock_result

        # Execute search with filters
        hits = await search_service.bm25_search(
            query="test",
            top_k=5,
            entity_type="memory_card",
            tags=["finance"],
            namespace="test-namespace",
        )

        assert len(hits) == 1
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_bm25_search(self, search_service, mock_db):
        """Test batch BM25 search with multiple queries."""
        mock_entity = MagicMock()
        mock_entity.entity_id = uuid.uuid4()
        mock_entity.entity_type = "memory_card"
        mock_entity.name = "Test"
        mock_entity.when_to_use = "Test"
        mock_entity.tags = []
        mock_entity.channels = {"latest": uuid.uuid4()}
        mock_entity.deleted_at = None

        mock_result = MagicMock()
        mock_result.all.return_value = [(mock_entity, 0.5)]
        mock_db.execute.return_value = mock_result

        # Execute batch search
        results = await search_service.batch_bm25_search(
            queries=["query1", "query2", "query3"],
            top_k=5,
            entity_type="memory_card",
        )

        assert len(results) == 3
        assert all(len(r) == 1 for r in results)
        assert mock_db.execute.call_count == 3


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
        # Mock database response
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
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        # Execute search
        query_vector = [0.1] * 384  # Mock embedding
        hits = await search_service.vector_search(
            query_vector=query_vector,
            top_k=10,
            entity_type="memory_card",
        )

        assert len(hits) == 1
        assert hits[0]["name"] == "Test Entity"
        assert hits[0]["score"] == 0.95
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
        }

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        query_vector = [0.1] * 384
        hits = await search_service.vector_search(
            query_vector=query_vector,
            top_k=10,
            entity_type="memory_card",
            tags=["finance"],
            namespace="test-ns",
        )

        assert len(hits) == 1
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_vector_search_invalid_dimension(self, search_service, mock_db):
        """Test vector search with wrong dimension."""
        query_vector = [0.1] * 100  # Wrong dimension

        with pytest.raises(ValueError, match="query_vector"):
            await search_service.vector_search(
                query_vector=query_vector,
                top_k=10,
                entity_type="memory_card",
            )

    @pytest.mark.asyncio
    async def test_batch_vector_search_raises_error(self, search_service, mock_db):
        """Test that batch vector search raises error (requires embedding service)."""
        with pytest.raises(ValueError, match="embedding service"):
            await search_service.batch_vector_search(
                queries=["query1", "query2"],
                top_k=10,
                entity_type="memory_card",
            )


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

    def test_unified_search_vector_missing_vector(self, client):
        """Test that vector search requires query_vector."""
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
