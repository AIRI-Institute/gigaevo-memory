"""Unit tests for EntityService and cursor utilities."""

import base64
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.entity_service import (
    VALID_ENTITY_TYPES,
    EntityService,
    _decode_cursor,
    _encode_cursor,
    compute_etag,
)


class TestComputeETag:
    """Tests for ETag computation."""

    def test_compute_etag_basic(self):
        """Test basic ETag computation."""
        content = {"name": "test", "value": 123}
        etag = compute_etag(content)
        
        assert isinstance(etag, str)
        assert len(etag) == 64  # SHA-256 hex
        
    def test_compute_etag_consistency(self):
        """Test ETag is consistent for same content."""
        content = {"a": 1, "b": 2}
        etag1 = compute_etag(content)
        etag2 = compute_etag(content)
        
        assert etag1 == etag2
        
    def test_compute_etag_key_order_independence(self):
        """Test ETag is independent of key order."""
        content1 = {"a": 1, "b": 2, "c": 3}
        content2 = {"c": 3, "a": 1, "b": 2}
        
        etag1 = compute_etag(content1)
        etag2 = compute_etag(content2)
        
        assert etag1 == etag2
        
    def test_compute_etag_nested_content(self):
        """Test ETag with nested content."""
        content = {
            "metadata": {"name": "test"},
            "steps": [{"id": 1}, {"id": 2}]
        }
        etag = compute_etag(content)
        
        assert isinstance(etag, str)
        assert len(etag) == 64


class TestCursorEncoding:
    """Tests for cursor encoding/decoding."""

    def test_encode_decode_cursor(self):
        """Test cursor encoding and decoding roundtrip."""
        created_at = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        entity_id = uuid.uuid4()
        entity_type = "chain"
        channel = "latest"
        
        cursor = _encode_cursor(created_at, entity_id, entity_type, channel)
        
        # Verify cursor is base64-like string
        assert isinstance(cursor, str)
        assert len(cursor) > 0
        
        # Decode and verify
        decoded_at, decoded_id = _decode_cursor(cursor, entity_type=entity_type, channel=channel)
        
        assert decoded_at == created_at
        assert decoded_id == entity_id
        
    def test_encode_cursor_contains_version(self):
        """Test encoded cursor contains version info."""
        created_at = datetime.now(timezone.utc)
        entity_id = uuid.uuid4()
        
        cursor = _encode_cursor(created_at, entity_id, "chain", "latest")
        
        # Decode base64 and check structure
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(f"{cursor}{padding}")
        payload = json.loads(raw.decode("utf-8"))
        
        assert payload["v"] == 1  # Cursor version
        assert payload["entity_type"] == "chain"
        assert payload["channel"] == "latest"
        assert payload["entity_id"] == str(entity_id)
        
    def test_decode_cursor_wrong_entity_type(self):
        """Test decoding cursor with wrong entity type raises error."""
        created_at = datetime.now(timezone.utc)
        entity_id = uuid.uuid4()
        
        cursor = _encode_cursor(created_at, entity_id, "chain", "latest")
        
        with pytest.raises(ValueError, match="entity type mismatch"):
            _decode_cursor(cursor, entity_type="step", channel="latest")
            
    def test_decode_cursor_wrong_channel(self):
        """Test decoding cursor with wrong channel raises error."""
        created_at = datetime.now(timezone.utc)
        entity_id = uuid.uuid4()
        
        cursor = _encode_cursor(created_at, entity_id, "chain", "latest")
        
        with pytest.raises(ValueError, match="channel mismatch"):
            _decode_cursor(cursor, entity_type="chain", channel="stable")
            
    def test_decode_invalid_cursor(self):
        """Test decoding invalid cursor raises error."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            _decode_cursor("not-a-valid-cursor", entity_type="chain", channel="latest")
            
    def test_decode_empty_cursor(self):
        """Test decoding empty cursor raises error."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            _decode_cursor("", entity_type="chain", channel="latest")
            
    def test_decode_non_object_payload(self):
        """Test decoding cursor with non-object payload raises error."""
        # Create cursor with array payload
        payload = json.dumps(["not", "an", "object"])
        raw = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        
        with pytest.raises(ValueError, match="Invalid cursor"):
            _decode_cursor(raw, entity_type="chain", channel="latest")
            
    def test_decode_wrong_version(self):
        """Test decoding cursor with wrong version raises error."""
        payload = json.dumps({
            "v": 999,  # Wrong version
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entity_id": str(uuid.uuid4()),
            "entity_type": "chain",
            "channel": "latest"
        })
        raw = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        
        with pytest.raises(ValueError, match="Unsupported cursor version"):
            _decode_cursor(raw, entity_type="chain", channel="latest")
            
    def test_decode_naive_datetime(self):
        """Test decoding cursor with naive datetime raises error."""
        payload = json.dumps({
            "v": 1,
            "created_at": "2026-01-15T10:30:00",  # No timezone
            "entity_id": str(uuid.uuid4()),
            "entity_type": "chain",
            "channel": "latest"
        })
        raw = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        
        with pytest.raises(ValueError, match="timezone-aware"):
            _decode_cursor(raw, entity_type="chain", channel="latest")


class TestValidEntityTypes:
    """Tests for VALID_ENTITY_TYPES constant."""

    def test_valid_entity_types_structure(self):
        """Test VALID_ENTITY_TYPES has correct structure."""
        assert "chains" in VALID_ENTITY_TYPES
        assert "steps" in VALID_ENTITY_TYPES
        assert "agents" in VALID_ENTITY_TYPES
        assert "memory_cards" in VALID_ENTITY_TYPES
        
        assert VALID_ENTITY_TYPES["chains"] == "chain"
        assert VALID_ENTITY_TYPES["steps"] == "step"
        assert VALID_ENTITY_TYPES["agents"] == "agent"
        assert VALID_ENTITY_TYPES["memory_cards"] == "memory_card"


class TestEntityServiceBasic:
    """Basic tests for EntityService initialization."""

    def test_entity_service_init(self):
        """Test EntityService can be initialized with mock DB."""
        mock_db = AsyncMock()
        service = EntityService(mock_db)
        
        assert service.db is mock_db
