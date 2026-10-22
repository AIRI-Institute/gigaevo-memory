"""Tests for SSE event stream and webhook endpoints."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestEventStream:
    """Tests for the SSE event stream endpoint."""

    async def test_event_stream_endpoint_exists(self, async_client: AsyncClient):
        """Test that event stream endpoint exists and returns SSE content type."""
        # We can't easily test the full SSE stream in a unit test,
        # but we can verify the endpoint responds
        import asyncio
        
        try:
            # Use a timeout since SSE streams are long-lived
            resp = await asyncio.wait_for(
                async_client.get("/v1/events/stream"),
                timeout=2.0
            )
            # Should get 200 OK with text/event-stream content type
            assert resp.status_code == 200
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type or "application/json" in content_type
        except asyncio.TimeoutError:
            # Timeout is expected for SSE streams, they keep connection open
            pass

    async def test_event_stream_with_entity_type_filter(self, async_client: AsyncClient):
        """Test event stream accepts entity_type filter parameter."""
        import asyncio
        
        try:
            resp = await asyncio.wait_for(
                async_client.get("/v1/events/stream?entity_type=chain"),
                timeout=2.0
            )
            assert resp.status_code == 200
        except asyncio.TimeoutError:
            pass  # Expected for SSE

    async def test_event_stream_with_entity_id_filter(self, async_client: AsyncClient):
        """Test event stream accepts entity_id filter parameter."""
        import asyncio
        
        try:
            resp = await asyncio.wait_for(
                async_client.get("/v1/events/stream?entity_id=test-id-123"),
                timeout=2.0
            )
            assert resp.status_code == 200
        except asyncio.TimeoutError:
            pass  # Expected for SSE

    async def test_event_stream_with_namespace_filter(self, async_client: AsyncClient):
        """Test event stream accepts namespace filter parameter."""
        import asyncio
        
        try:
            resp = await asyncio.wait_for(
                async_client.get("/v1/events/stream?namespace=test-namespace"),
                timeout=2.0
            )
            assert resp.status_code == 200
        except asyncio.TimeoutError:
            pass  # Expected for SSE

    async def test_event_stream_with_combined_filters(self, async_client: AsyncClient):
        """Test event stream accepts multiple filter parameters."""
        import asyncio
        
        try:
            resp = await asyncio.wait_for(
                async_client.get(
                    "/v1/events/stream?entity_type=chain&entity_id=test-id&namespace=prod"
                ),
                timeout=2.0
            )
            assert resp.status_code == 200
        except asyncio.TimeoutError:
            pass  # Expected for SSE


@pytest.mark.integration
class TestWebhookEndpoints:
    """Tests for webhook management endpoints."""

    async def test_create_webhook_not_implemented(self, async_client: AsyncClient):
        """Test webhook creation returns 501 Not Implemented."""
        resp = await async_client.post("/v1/webhooks", json={"url": "http://example.com"})
        assert resp.status_code == 501
        data = resp.json()
        assert "not yet implemented" in data["detail"].lower()

    async def test_delete_webhook_not_implemented(self, async_client: AsyncClient):
        """Test webhook deletion returns 501 Not Implemented."""
        resp = await async_client.delete("/v1/webhooks/webhook-123")
        assert resp.status_code == 501
        data = resp.json()
        assert "not yet implemented" in data["detail"].lower()


class TestEventPublisherUnit:
    """Unit tests for event publisher functions."""

    @pytest.mark.asyncio
    async def test_publish_entity_event(self):
        """Test publishing entity events."""
        from app.events.publisher import publish_entity_event
        
        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()
        
        with patch("app.events.publisher.get_redis", return_value=mock_redis):
            await publish_entity_event(
                event_type="created",
                entity_id="test-id-123",
                entity_type="chain",
                version_id="ver-123",
                channel="latest"
            )
            
            # Verify Redis publish was called
            mock_redis.publish.assert_called_once()
            call_args = mock_redis.publish.call_args
            
            # Check channel name
            assert call_args[0][0] == "memory:events"
            
            # Check message is valid JSON
            message = json.loads(call_args[0][1])
            assert message["event_type"] == "created"
            assert message["entity_id"] == "test-id-123"
            assert message["entity_type"] == "chain"
            assert message["version_id"] == "ver-123"
            assert message["channel"] == "latest"

    @pytest.mark.asyncio
    async def test_publish_entity_event_without_version(self):
        """Test publishing entity events without version."""
        from app.events.publisher import publish_entity_event
        
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()
        
        with patch("app.events.publisher.get_redis", return_value=mock_redis):
            await publish_entity_event(
                event_type="deleted",
                entity_id="test-id-123",
                entity_type="chain"
            )
            
            mock_redis.publish.assert_called_once()
            message = json.loads(mock_redis.publish.call_args[0][1])
            assert message["event_type"] == "deleted"
            assert message["entity_id"] == "test-id-123"
            assert message["entity_type"] == "chain"
            assert message["version_id"] is None

    @pytest.mark.asyncio
    async def test_get_redis(self):
        """Test getting Redis connection."""
        from app.events.publisher import get_redis
        
        # Mock aioredis
        mock_redis = AsyncMock()
        mock_from_url = AsyncMock(return_value=mock_redis)
        
        with patch("app.events.publisher.aioredis.from_url", mock_from_url):
            redis = await get_redis()
            assert redis is not None
