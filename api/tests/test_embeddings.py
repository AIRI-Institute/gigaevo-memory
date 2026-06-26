"""Tests for embeddings endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestEmbeddingsEndpoint:
    """Tests for the /v1/embeddings endpoint."""

    async def test_embeddings_when_disabled(self, async_client: AsyncClient, monkeypatch):
        """Test embeddings endpoint returns 503 when vector search is disabled."""
        from app.config import settings
        
        # Store original value
        original = settings.enable_vector_search
        
        try:
            # Disable vector search
            monkeypatch.setattr(settings, "enable_vector_search", False)
            
            resp = await async_client.post(
                "/v1/embeddings",
                json={"texts": ["hello world"]}
            )
            
            assert resp.status_code == 503
            data = resp.json()
            assert "vector search is not enabled" in data["detail"].lower()
        finally:
            # Restore original
            monkeypatch.setattr(settings, "enable_vector_search", original)

    async def test_embeddings_empty_texts_validation(self, async_client: AsyncClient, monkeypatch):
        """Test embeddings endpoint validates empty texts array."""
        from app.config import settings
        
        # Skip if vector search is not enabled in environment
        if not settings.enable_vector_search:
            pytest.skip("Vector search not enabled")
        
        resp = await async_client.post(
            "/v1/embeddings",
            json={"texts": []}
        )
        
        # Should fail validation (422) due to min_length constraint
        assert resp.status_code == 422

    async def test_embeddings_too_many_texts_validation(self, async_client: AsyncClient, monkeypatch):
        """Test embeddings endpoint validates max texts limit."""
        from app.config import settings
        
        if not settings.enable_vector_search:
            pytest.skip("Vector search not enabled")
        
        # Try to embed more than 100 texts
        resp = await async_client.post(
            "/v1/embeddings",
            json={"texts": ["text"] * 101}
        )
        
        # Should fail validation (422) due to max_length constraint
        assert resp.status_code == 422

    async def test_embeddings_missing_texts_field(self, async_client: AsyncClient, monkeypatch):
        """Test embeddings endpoint requires texts field."""
        from app.config import settings
        
        if not settings.enable_vector_search:
            pytest.skip("Vector search not enabled")
        
        resp = await async_client.post(
            "/v1/embeddings",
            json={}
        )
        
        # Should fail validation (422)
        assert resp.status_code == 422


class TestEmbeddingsRequestResponse:
    """Unit tests for embeddings request/response models."""

    def test_embeddings_request_validation(self):
        """Test EmbeddingsRequest validation."""
        from app.routers.embeddings import EmbeddingsRequest
        
        # Valid request
        req = EmbeddingsRequest(texts=["hello", "world"])
        assert req.texts == ["hello", "world"]
        assert req.model is None
        
        # Valid request with model
        req = EmbeddingsRequest(texts=["hello"], model="custom-model")
        assert req.model == "custom-model"

    def test_embeddings_request_empty_texts_raises(self):
        """Test EmbeddingsRequest raises on empty texts."""
        from app.routers.embeddings import EmbeddingsRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            EmbeddingsRequest(texts=[])

    def test_embeddings_request_too_many_texts_raises(self):
        """Test EmbeddingsRequest raises on too many texts."""
        from app.routers.embeddings import EmbeddingsRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            EmbeddingsRequest(texts=["text"] * 101)

    def test_embeddings_response_creation(self):
        """Test EmbeddingsResponse creation."""
        from app.routers.embeddings import EmbeddingsResponse
        
        resp = EmbeddingsResponse(
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            model="test-model",
            dimension=3
        )
        
        assert len(resp.embeddings) == 2
        assert resp.model == "test-model"
        assert resp.dimension == 3


class TestEmbeddingsEndpointUnit:
    """Unit tests for embeddings endpoint logic."""

    @pytest.mark.asyncio
    async def test_create_embeddings_service_error(self):
        """Test handling of embedding service errors."""
        from app.routers.embeddings import create_embeddings
        from app.routers.embeddings import EmbeddingsRequest
        from fastapi import HTTPException
        
        # Mock settings
        with patch("app.routers.embeddings.settings") as mock_settings:
            mock_settings.enable_vector_search = True
            
            # Mock embedding service that raises an error
            mock_service = AsyncMock()
            mock_service.embed_batch.side_effect = Exception("Service error")
            
            with patch("app.routers.embeddings.EmbeddingService.create", return_value=mock_service):
                req = EmbeddingsRequest(texts=["hello"])
                
                with pytest.raises(HTTPException) as exc_info:
                    await create_embeddings(req)
                
                assert exc_info.value.status_code == 503
                assert "embedding service error" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_create_embeddings_success(self):
        """Test successful embeddings generation."""
        from app.routers.embeddings import create_embeddings
        from app.routers.embeddings import EmbeddingsRequest
        
        with patch("app.routers.embeddings.settings") as mock_settings:
            mock_settings.enable_vector_search = True
            mock_settings.embedding_model = "test-model"
            
            # Mock embedding service
            mock_service = AsyncMock()
            mock_service.embed_batch.return_value = [[0.1, 0.2, 0.3]]
            mock_service.dimension = 3
            
            with patch("app.routers.embeddings.EmbeddingService.create", return_value=mock_service):
                req = EmbeddingsRequest(texts=["hello"])
                resp = await create_embeddings(req)
                
                assert resp.embeddings == [[0.1, 0.2, 0.3]]
                assert resp.model == "test-model"
                assert resp.dimension == 3

    @pytest.mark.asyncio
    async def test_create_embeddings_with_custom_model(self):
        """Test embeddings with custom model override."""
        from app.routers.embeddings import create_embeddings
        from app.routers.embeddings import EmbeddingsRequest
        
        with patch("app.routers.embeddings.settings") as mock_settings:
            mock_settings.enable_vector_search = True
            mock_settings.embedding_model = "default-model"
            
            mock_service = AsyncMock()
            mock_service.embed_batch.return_value = [[0.1, 0.2]]
            mock_service.dimension = 2
            
            with patch("app.routers.embeddings.EmbeddingService.create", return_value=mock_service):
                req = EmbeddingsRequest(texts=["hello"], model="custom-model")
                resp = await create_embeddings(req)
                
                assert resp.model == "custom-model"
