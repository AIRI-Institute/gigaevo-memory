"""Tests for exception handling in MemoryClient."""

import httpx
import pytest
import respx

from gigaevo_memory import (
    ConflictError,
    ConnectionError as MemoryConnectionError,
    MemoryError,
    NotFoundError,
    ValidationError,
)
from gigaevo_memory.client import MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


class TestNotFoundError:
    """Tests for NotFoundError exception."""

    def test_not_found_error_is_memory_error(self):
        """Test NotFoundError is subclass of MemoryError."""
        assert issubclass(NotFoundError, MemoryError)

    def test_not_found_error_message(self):
        """Test NotFoundError stores message."""
        error = NotFoundError("Entity not found")
        assert str(error) == "Entity not found"

    def test_not_found_on_404(self, client):
        """Test 404 response raises NotFoundError."""
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/missing").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"})
            )
            with pytest.raises(NotFoundError):
                client.get_chain_dict("missing")


class TestConflictError:
    """Tests for ConflictError exception."""

    def test_conflict_error_is_memory_error(self):
        """Test ConflictError is subclass of MemoryError."""
        assert issubclass(ConflictError, MemoryError)

    def test_conflict_on_409(self, client):
        """Test 409 response raises ConflictError."""
        with respx.mock:
            respx.put("http://test-api:8000/v1/chains/entity-123").mock(
                return_value=httpx.Response(409, json={"detail": "Conflict"})
            )
            with pytest.raises(ConflictError):
                client.save_chain({"name": "test"}, name="test", entity_id="entity-123")

    def test_conflict_on_412(self, client):
        """Test 412 response raises ConflictError."""
        with respx.mock:
            respx.put("http://test-api:8000/v1/chains/entity-123").mock(
                return_value=httpx.Response(412, json={"detail": "Precondition failed"})
            )
            with pytest.raises(ConflictError):
                client.save_chain({"name": "test"}, name="test", entity_id="entity-123")


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_is_memory_error(self):
        """Test ValidationError is subclass of MemoryError."""
        assert issubclass(ValidationError, MemoryError)

    def test_validation_on_422(self, client):
        """Test 422 response raises ValidationError."""
        with respx.mock:
            respx.post("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(422, json={"detail": "Validation failed"})
            )
            with pytest.raises(ValidationError):
                client.save_chain({"name": "test"}, name="test")


class TestConnectionError:
    """Tests for ConnectionError exception."""

    def test_connection_error_is_memory_error(self):
        """Test ConnectionError is subclass of MemoryError."""
        assert issubclass(MemoryConnectionError, MemoryError)

    def test_connection_error_message(self):
        """Test ConnectionError stores message."""
        error = MemoryConnectionError("Cannot connect to server")
        assert str(error) == "Cannot connect to server"


class TestHttpStatusErrorPropagation:
    """Tests for other HTTP errors that should use httpx exceptions."""

    def test_500_error_uses_httpx(self, client):
        """Test 500 errors use httpx.HTTPStatusError."""
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/entity-123").mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            with pytest.raises(httpx.HTTPStatusError):
                client.get_chain_dict("entity-123")

    def test_400_error_uses_httpx(self, client):
        """Test 400 errors use httpx.HTTPStatusError."""
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/entity-123").mock(
                return_value=httpx.Response(400, text="Bad Request")
            )
            with pytest.raises(httpx.HTTPStatusError):
                client.get_chain_dict("entity-123")
