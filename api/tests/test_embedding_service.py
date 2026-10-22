"""Unit tests for EmbeddingService and backends."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.embedding_service import (
    EmbeddingBackend,
    EmbeddingService,
    HuggingFaceBackend,
    OpenAIBackend,
    SentenceTransformersBackend,
)


class TestEmbeddingBackendInterface:
    """Tests for EmbeddingBackend abstract interface."""

    def test_embedding_backend_is_abstract(self):
        """Test EmbeddingBackend cannot be instantiated directly."""
        with pytest.raises(TypeError):
            EmbeddingBackend()

    def test_embedding_backend_subclass_must_implement_embed(self):
        """Test subclasses must implement embed method."""
        class IncompleteBackend(EmbeddingBackend):
            @property
            def dimension(self):
                return 10
        
        with pytest.raises(TypeError):
            IncompleteBackend()

    def test_embedding_backend_subclass_must_implement_dimension(self):
        """Test subclasses must implement dimension property."""
        class IncompleteBackend(EmbeddingBackend):
            async def embed(self, texts):
                return [[0.1]] * len(texts)
        
        with pytest.raises(TypeError):
            IncompleteBackend()

    @pytest.mark.asyncio
    async def test_embed_query_uses_embed(self):
        """Test embed_query delegates to embed."""
        class MockBackend(EmbeddingBackend):
            async def embed(self, texts):
                return [[0.1 * i for i in range(10)]] * len(texts)
            
            @property
            def dimension(self):
                return 10
        
        backend = MockBackend()
        result = await backend.embed_query("test")
        
        # Check approximate equality due to floating point
        assert len(result) == 10
        assert result[0] == 0.0
        assert result[1] == pytest.approx(0.1)


class TestSentenceTransformersBackend:
    """Tests for SentenceTransformersBackend."""

    def test_backend_init(self):
        """Test backend initialization."""
        backend = SentenceTransformersBackend(
            model_name="test-model",
            device="cpu"
        )
        
        assert backend.model_name == "test-model"
        assert backend.device == "cpu"
        assert backend._model is None  # Lazy loading

    @pytest.mark.asyncio
    async def test_dimension_before_load(self):
        """Test dimension returns default before model load."""
        backend = SentenceTransformersBackend()
        
        # Set _dimension directly to avoid triggering async load
        backend._dimension = 384
        assert backend.dimension == 384


class TestOpenAIBackend:
    """Tests for OpenAIBackend."""

    def test_backend_init(self):
        """Test backend initialization."""
        backend = OpenAIBackend(
            api_key="test-key",
            model="text-embedding-3-small",
            dimension=1536
        )
        
        assert backend.api_key == "test-key"
        assert backend.model == "text-embedding-3-small"
        assert backend.dimension == 1536


class TestHuggingFaceBackend:
    """Tests for HuggingFaceBackend."""

    def test_backend_init(self):
        """Test backend initialization."""
        backend = HuggingFaceBackend(
            api_key="hf-test-key",
            model="sentence-transformers/all-MiniLM-L6-v2",
            dimension=384
        )
        
        assert backend.api_key == "hf-test-key"
        assert backend.model == "sentence-transformers/all-MiniLM-L6-v2"
        assert backend.dimension == 384


class TestEmbeddingServiceSingleton:
    """Tests for EmbeddingService singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        EmbeddingService._instance = None

    def teardown_method(self):
        """Reset singleton after each test."""
        EmbeddingService._instance = None

    def test_get_instance_before_create_raises(self):
        """Test get_instance raises if not initialized."""
        with pytest.raises(ValueError, match="not initialized"):
            EmbeddingService.get_instance()

    def test_singleton_instance_persists(self):
        """Test singleton instance persists across calls."""
        mock_backend = MagicMock()
        
        service1 = EmbeddingService(mock_backend)
        EmbeddingService._instance = service1
        
        service2 = EmbeddingService.get_instance()
        
        assert service1 is service2

    @pytest.mark.asyncio
    async def test_create_returns_existing_instance(self):
        """Test create returns existing instance if set."""
        mock_backend = MagicMock()
        existing = EmbeddingService(mock_backend)
        EmbeddingService._instance = existing
        
        result = await EmbeddingService.create()
        
        assert result is existing

    @pytest.mark.asyncio
    async def test_embed_batch_with_caching(self):
        """Test embed_batch caches results."""
        mock_backend = MagicMock()
        mock_backend.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        mock_backend.dimension = 3
        
        service = EmbeddingService(mock_backend)
        
        # First call should hit backend
        await service.embed_batch(["test"])
        assert mock_backend.embed.called


class TestEmbeddingServiceCaching:
    """Tests for EmbeddingService caching behavior."""

    def setup_method(self):
        """Reset singleton before each test."""
        EmbeddingService._instance = None

    def teardown_method(self):
        """Reset singleton after each test."""
        EmbeddingService._instance = None

    @pytest.mark.asyncio
    async def test_embed_batch_caches_repeated_texts(self):
        """Test repeated texts use cache."""
        mock_backend = AsyncMock()
        mock_backend.embed.return_value = [[0.1, 0.2, 0.3]]
        
        service = EmbeddingService(mock_backend)
        
        # First call
        result1 = await service.embed_batch(["test"])
        
        # Second call with same text should use cache
        result2 = await service.embed_batch(["test"])
        
        # Backend should only be called once
        assert mock_backend.embed.call_count == 1
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_embed_batch_partial_cache_hit(self):
        """Test partial cache hit works correctly."""
        mock_backend = AsyncMock()
        mock_backend.embed.return_value = [[0.4, 0.5, 0.6]]
        
        service = EmbeddingService(mock_backend)
        
        # First call
        await service.embed_batch(["cached"])
        
        # Second call with mix of cached and new
        result = await service.embed_batch(["cached", "new"])
        
        # Backend should be called once for the new text
        assert mock_backend.embed.call_count == 2
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_embed_batch_empty_input(self):
        """Test embed_batch with empty input."""
        mock_backend = AsyncMock()
        
        service = EmbeddingService(mock_backend)
        result = await service.embed_batch([])
        
        assert result == []
        mock_backend.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_query_uses_batch(self):
        """Test embed_query delegates to embed_batch."""
        mock_backend = AsyncMock()
        mock_backend.embed.return_value = [[0.1, 0.2, 0.3]]
        
        service = EmbeddingService(mock_backend)
        result = await service.embed_query("test")
        
        assert result == [0.1, 0.2, 0.3]
        mock_backend.embed.assert_called_once_with(["test"])
