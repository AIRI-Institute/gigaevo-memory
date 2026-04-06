"""Tests for client search functionality with SearchType enum."""

import pytest
from unittest.mock import MagicMock
import httpx

from gigaevo_memory import (
    MemoryClient,
    SearchType,
    EmbeddingProvider,
    MemoryCardSpec,
)
from gigaevo_memory.embeddings import (
    SentenceTransformersProvider,
)


class TestSearchType:
    """Tests for SearchType enum."""

    def test_search_type_values(self):
        """Test SearchType enum values."""
        assert SearchType.VECTOR.value == "vector"
        assert SearchType.BM25.value == "bm25"

    def test_search_type_from_string(self):
        """Test creating SearchType from string."""
        assert SearchType("vector") == SearchType.VECTOR
        assert SearchType("bm25") == SearchType.BM25


class MockEmbeddingProvider(EmbeddingProvider):
    """Mock embedding provider for testing."""

    def __init__(self, dimension: int = 384):
        self._dimension = dimension
        self.call_count = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return mock embeddings."""
        self.call_count += 1
        return [[0.1] * self._dimension for _ in texts]

    @property
    def dimension(self) -> int:
        return self._dimension


class TestMemoryClientSearch:
    """Tests for MemoryClient search methods."""

    @pytest.fixture
    def mock_http(self):
        """Create mock HTTP client."""
        mock = MagicMock(spec=httpx.Client)
        mock.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"hits": [], "total": 0}
        )
        mock.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"hits": [], "search_type": "bm25", "total": 0}
        )
        return mock

    @pytest.fixture
    def client(self, mock_http):
        """Create client with mock HTTP."""
        client = MemoryClient(base_url="http://test")
        client._http = mock_http
        return client

    def test_search_bm25_basic(self, client, mock_http):
        """Test basic BM25 search."""
        # Mock response
        mock_http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "hits": [
                    {
                        "entity_id": "test-id",
                        "entity_type": "memory_card",
                        "name": "Test",
                        "score": 0.8,
                        "channel": "latest",
                        "version_id": "v1",
                        "tags": [],
                        "when_to_use": None,
                        "content": {
                            "description": "Test description",
                            "explanation": "",
                            "keywords": [],
                        },
                    }
                ],
                "search_type": "bm25",
                "total": 1,
            }
        )

        results = client.search(
            query="test query",
            search_type=SearchType.BM25,
            top_k=10,
        )

        assert len(results) == 1
        assert isinstance(results[0], MemoryCardSpec)
        mock_http.post.assert_called_once()

    def test_search_vector_with_provider(self, client, mock_http):
        """Test vector search with custom embedding provider."""
        provider = MockEmbeddingProvider()

        # Mock response
        mock_http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "hits": [
                    {
                        "entity_id": "test-id",
                        "entity_type": "memory_card",
                        "name": "Test",
                        "score": 0.95,
                        "channel": "latest",
                        "version_id": "v1",
                        "tags": [],
                        "when_to_use": None,
                        "content": {
                            "description": "Test",
                            "explanation": "",
                            "keywords": [],
                        },
                    }
                ],
                "search_type": "vector",
                "total": 1,
            }
        )

        results = client.search(
            query="semantic query",
            search_type=SearchType.VECTOR,
            top_k=5,
            embedding_provider=provider,
        )

        assert len(results) == 1
        assert provider.call_count == 1  # Embedding was called once

    def test_batch_search_bm25(self, client, mock_http):
        """Test batch BM25 search."""
        mock_http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "results": [
                    [
                        {
                            "entity_id": "id-0",
                            "entity_type": "memory_card",
                            "name": "Result 0",
                            "score": 0.8,
                            "channel": "latest",
                            "version_id": "v1",
                            "tags": [],
                            "when_to_use": None,
                            "content": {"description": "Test", "explanation": "", "keywords": []},
                        }
                    ],
                    [
                        {
                            "entity_id": "id-1",
                            "entity_type": "memory_card",
                            "name": "Result 1",
                            "score": 0.8,
                            "channel": "latest",
                            "version_id": "v1",
                            "tags": [],
                            "when_to_use": None,
                            "content": {"description": "Test", "explanation": "", "keywords": []},
                        }
                    ],
                    [
                        {
                            "entity_id": "id-2",
                            "entity_type": "memory_card",
                            "name": "Result 2",
                            "score": 0.8,
                            "channel": "latest",
                            "version_id": "v1",
                            "tags": [],
                            "when_to_use": None,
                            "content": {"description": "Test", "explanation": "", "keywords": []},
                        }
                    ],
                ],
                "search_type": "bm25",
                "total_queries": 3,
            },
        )

        results = client.batch_search(
            queries=["query1", "query2", "query3"],
            search_type=SearchType.BM25,
            top_k=5,
        )

        assert len(results) == 3
        assert all(len(r) == 1 for r in results)
        mock_http.post.assert_called_once_with(
            "/v1/search/batch",
            json={
                "search_type": "bm25",
                "queries": ["query1", "query2", "query3"],
                "top_k": 5,
                "entity_type": "memory_card",
                "channel": "latest",
            },
        )

    def test_batch_search_vector(self, client, mock_http):
        """Test batch vector search with embedding provider."""
        provider = MockEmbeddingProvider()

        mock_http.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "results": [[], [], []],
                "search_type": "vector",
                "total_queries": 3,
            },
        )

        results = client.batch_search(
            queries=["q1", "q2", "q3"],
            search_type=SearchType.VECTOR,
            top_k=5,
            embedding_provider=provider,
        )

        assert len(results) == 3
        assert provider.call_count == 1  # Batch embed called once
        mock_http.post.assert_called_once()
        _, kwargs = mock_http.post.call_args
        assert kwargs["json"]["search_type"] == "vector"
        assert kwargs["json"]["queries"] == ["q1", "q2", "q3"]
        assert kwargs["json"]["query_vectors"] == [[0.1] * provider.dimension for _ in range(3)]

    def test_batch_search_empty_queries(self, client, mock_http):
        """Test batch search with empty queries returns empty."""
        results = client.batch_search(
            queries=[],
            search_type=SearchType.BM25,
            top_k=5,
        )

        assert results == []
        mock_http.post.assert_not_called()


class TestEmbeddingProviders:
    """Tests for embedding providers."""

    def test_mock_provider(self):
        """Test mock embedding provider."""
        provider = MockEmbeddingProvider(dimension=128)

        embeddings = provider.embed(["test1", "test2"])

        assert len(embeddings) == 2
        assert len(embeddings[0]) == 128
        assert provider.dimension == 128

    def test_mock_provider_single_query(self):
        """Test embedding single query."""
        provider = MockEmbeddingProvider()

        embedding = provider.embed_query("test query")

        assert len(embedding) == 384
        assert provider.call_count == 1

    def test_sentence_transformers_provider_init(self):
        """Test SentenceTransformers provider initialization."""
        # Just test that provider can be created without importing the module
        provider = SentenceTransformersProvider(model_name="test-model", device="cpu")

        assert provider.model_name == "test-model"
        assert provider.device == "cpu"
        assert provider._model is None  # Lazy loading
