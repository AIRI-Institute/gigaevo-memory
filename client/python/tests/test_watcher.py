"""Tests for SSE watcher functionality."""

import json
from unittest.mock import MagicMock, patch


from gigaevo_memory.watcher import Subscription


class TestSubscriptionLifecycle:
    """Tests for Subscription lifecycle."""

    def test_subscription_init(self):
        """Test Subscription initialization."""
        mock_client = MagicMock()
        callback = MagicMock()
        
        sub = Subscription(
            client=mock_client,
            entity_id="test-entity",
            entity_type="chain",
            callback=callback
        )
        
        assert sub._client is mock_client
        assert sub._entity_id == "test-entity"
        assert sub._entity_type == "chain"
        assert sub._callback is callback
        assert sub._thread is None
        assert not sub.is_active

    def test_subscription_start_creates_thread(self):
        """Test start() creates background thread."""
        mock_client = MagicMock()
        mock_client._base_url = "http://test"
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        
        # Mock _listen to block until stop_event is set
        def mock_listen():
            sub._stop_event.wait(timeout=1)
        
        with patch.object(sub, '_listen', side_effect=mock_listen):
            sub.start()
            
            assert sub._thread is not None
            assert sub._thread.daemon is True
            # Give thread time to start
            import time
            time.sleep(0.01)
            assert sub.is_active
            
            sub.stop()

    def test_subscription_stop_sets_stop_event(self):
        """Test stop() sets stop event."""
        mock_client = MagicMock()
        mock_client._base_url = "http://test"
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        
        # Mock _listen to block until stop_event is set
        def mock_listen():
            sub._stop_event.wait(timeout=1)
        
        with patch.object(sub, '_listen', side_effect=mock_listen):
            sub.start()
            assert not sub._stop_event.is_set()
            
            sub.stop()
            assert sub._stop_event.is_set()

    def test_subscription_stop_without_start(self):
        """Test stop() without start() doesn't crash."""
        mock_client = MagicMock()
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        sub.stop()  # Should not raise


class TestEventHandling:
    """Tests for event handling."""

    def test_handle_entity_changed_event(self):
        """Test handling entity_changed event."""
        mock_client = MagicMock()
        mock_client.get_chain_dict.return_value = {"name": "updated"}
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        
        # Set up _client reference on sub
        sub._client = mock_client
        
        event_data = json.dumps({
            "event_type": "updated",
            "entity_id": "entity-123",
            "entity_type": "chain"
        })
        
        # Mock chain_from_content to avoid CARL dependency
        with patch('gigaevo_memory.watcher.chain_from_content', return_value={"name": "updated"}):
            sub._handle_event(event_data)
        
        # Callback should be invoked
        callback.assert_called_once()

    def test_handle_invalid_json(self):
        """Test handling invalid JSON doesn't crash."""
        mock_client = MagicMock()
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        sub._handle_event("not valid json")
        
        # Callback should not be invoked
        callback.assert_not_called()

    def test_handle_callback_error(self):
        """Test callback error doesn't crash listener."""
        mock_client = MagicMock()
        callback = MagicMock(side_effect=Exception("Callback error"))
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        
        event_data = json.dumps({"entity_id": "entity-123"})
        
        # Should not raise
        sub._handle_event(event_data)


class TestIsActiveProperty:
    """Tests for is_active property."""

    def test_is_active_false_before_start(self):
        """Test is_active is False before start."""
        mock_client = MagicMock()
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        assert not sub.is_active

    def test_is_active_true_after_start(self):
        """Test is_active is True after start."""
        mock_client = MagicMock()
        mock_client._base_url = "http://test"
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        
        # Mock _listen to block until stop_event is set
        def mock_listen():
            sub._stop_event.wait(timeout=1)
        
        with patch.object(sub, '_listen', side_effect=mock_listen):
            sub.start()
            # Give thread time to start
            import time
            time.sleep(0.01)
            assert sub.is_active
            sub.stop()

    def test_is_active_false_after_stop(self):
        """Test is_active is False after stop."""
        mock_client = MagicMock()
        mock_client._base_url = "http://test"
        callback = MagicMock()
        
        sub = Subscription(mock_client, "entity-123", "chain", callback)
        
        with patch.object(sub, '_listen'):
            sub.start()
            sub.stop()
            assert not sub.is_active
