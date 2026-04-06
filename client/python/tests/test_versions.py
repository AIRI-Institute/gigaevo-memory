"""Tests for version operations in MemoryClient."""

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient
from gigaevo_memory.models import DiffResponse, EntityRef, VersionDetail, VersionInfo


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


class TestListVersions:
    def test_list_versions_success(self, client):
        response = [
            {
                "version_id": "ver-2",
                "entity_id": "entity-123",
                "version_number": 2,
                "author": "alice",
                "change_summary": "Second version",
                "created_at": "2026-01-15T10:00:00Z"
            },
            {
                "version_id": "ver-1",
                "entity_id": "entity-123",
                "version_number": 1,
                "author": "bob",
                "change_summary": "First version",
                "created_at": "2026-01-14T10:00:00Z"
            }
        ]
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/entity-123/versions").mock(
                return_value=httpx.Response(200, json=response)
            )
            versions = client.list_versions("entity-123", entity_type="chain")
        
        assert len(versions) == 2
        assert all(isinstance(v, VersionInfo) for v in versions)
        assert versions[0].version_id == "ver-2"
        assert versions[1].version_id == "ver-1"

    def test_list_versions_with_limit(self, client):
        response = [{"version_id": "ver-1", "entity_id": "e1", "version_number": 1, "created_at": "2026-01-01T00:00:00Z"}]
        
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains/e1/versions").mock(
                return_value=httpx.Response(200, json=response)
            )
            client.list_versions("e1", entity_type="chain", limit=5)
        
        # Verify limit was passed as query param
        assert "limit=5" in str(route.calls[0].request.url)


class TestGetVersion:
    def test_get_version_success(self, client):
        response = {
            "version_id": "ver-1",
            "entity_id": "entity-123",
            "version_number": 1,
            "author": "alice",
            "change_summary": "Initial version",
            "created_at": "2026-01-15T10:00:00Z",
            "content": {"name": "test"},
            "meta": {"name": "test"}
        }
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/entity-123/versions/ver-1").mock(
                return_value=httpx.Response(200, json=response)
            )
            version = client.get_version("entity-123", "ver-1", entity_type="chain")
        
        assert isinstance(version, VersionDetail)
        assert version.version_id == "ver-1"
        assert version.content == {"name": "test"}


class TestDiffVersions:
    def test_diff_versions_success(self, client):
        # Note: The API returns patch as a JSON string, not a dict
        response = {
            "from_version": "ver-1",
            "to_version": "ver-2",
            "patch": {"op": "replace", "path": "/name", "value": "new_name"}
        }
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/entity-123/diff").mock(
                return_value=httpx.Response(200, json=response)
            )
            diff = client.diff_versions("entity-123", "ver-1", "ver-2", entity_type="chain")
        
        assert isinstance(diff, DiffResponse)
        assert diff.from_version == "ver-1"
        assert diff.to_version == "ver-2"


class TestRevert:
    def test_revert_success(self, client):
        response = {
            "entity_id": "entity-123",
            "entity_type": "chain",
            "version_id": "ver-3",
            "channel": "latest"
        }
        
        with respx.mock:
            respx.post("http://test-api:8000/v1/chains/entity-123/revert").mock(
                return_value=httpx.Response(200, json=response)
            )
            ref = client.revert("entity-123", "ver-1", entity_type="chain")
        
        assert isinstance(ref, EntityRef)
        assert ref.entity_id == "entity-123"
        assert ref.version_id == "ver-3"


class TestPinChannel:
    def test_pin_channel_success(self, client):
        response = {"status": "pinned"}
        
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/chains/entity-123/pin").mock(
                return_value=httpx.Response(200, json=response)
            )
            result = client.pin_channel("entity-123", "stable", "ver-1", entity_type="chain")
        
        assert result["status"] == "pinned"
        # Verify request body
        request_body = route.calls[0].request.content
        assert b"stable" in request_body
        assert b"ver-1" in request_body


class TestPromote:
    def test_promote_success(self, client):
        response = {"status": "promoted"}
        
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/chains/entity-123/promote").mock(
                return_value=httpx.Response(200, json=response)
            )
            result = client.promote("entity-123", from_channel="latest", to_channel="stable", entity_type="chain")
        
        assert result["status"] == "promoted"
        # Verify request body
        request_body = route.calls[0].request.content
        assert b"latest" in request_body
        assert b"stable" in request_body
