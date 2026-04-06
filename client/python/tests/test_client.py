"""Tests for MemoryClient CRUD operations."""


import gigaevo_memory
import gigaevo_memory.models as memory_models
import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient
from gigaevo_memory.exceptions import NotFoundError


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


class TestGetEntity:
    @respx.mock
    def test_get_chain_dict(self, client, sample_entity_response):
        respx.get("http://test-api:8000/v1/chains/550e8400-e29b-41d4-a716-446655440000").mock(
            return_value=httpx.Response(200, json=sample_entity_response)
        )
        result = client.get_chain_dict("550e8400-e29b-41d4-a716-446655440000")
        assert result["version"] == "1.1"
        assert len(result["steps"]) == 4

    @respx.mock
    def test_get_step_dict(self, client, sample_step_dict):
        resp = {
            "entity_type": "step",
            "entity_id": "aaa",
            "version_id": "bbb",
            "channel": "latest",
            "etag": "xyz",
            "meta": {},
            "content": sample_step_dict,
        }
        respx.get("http://test-api:8000/v1/steps/aaa").mock(
            return_value=httpx.Response(200, json=resp)
        )
        result = client.get_step_dict("aaa")
        assert result["step_type"] == "tool"
        assert result["step_config"]["tool_name"] == "fetch_data"

    @respx.mock
    def test_get_not_found_raises(self, client):
        respx.get("http://test-api:8000/v1/chains/missing").mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )
        with pytest.raises(NotFoundError):
            client.get_chain_dict("missing")


class TestPublicImports:
    def test_search_hit_not_exported(self):
        assert not hasattr(gigaevo_memory, "SearchHit")
        assert not hasattr(memory_models, "SearchHit")


class TestSaveEntity:
    @respx.mock
    def test_save_chain(self, client, sample_chain_dict):
        resp = {
            "entity_type": "chain",
            "entity_id": "new-id-123",
            "version_id": "ver-1",
            "channel": "latest",
            "etag": "abc",
            "meta": {"name": "test"},
            "content": sample_chain_dict,
        }
        respx.post("http://test-api:8000/v1/chains").mock(
            return_value=httpx.Response(201, json=resp)
        )
        ref = client.save_chain(
            sample_chain_dict, name="test", tags=["finance"], author="alice"
        )
        assert ref.entity_id == "new-id-123"
        assert ref.entity_type == "chain"

    @respx.mock
    def test_update_chain(self, client, sample_chain_dict):
        resp = {
            "entity_type": "chain",
            "entity_id": "existing-id",
            "version_id": "ver-2",
            "channel": "latest",
            "etag": "def",
            "meta": {"name": "updated"},
            "content": sample_chain_dict,
        }
        respx.put("http://test-api:8000/v1/chains/existing-id").mock(
            return_value=httpx.Response(200, json=resp)
        )
        ref = client.save_chain(
            sample_chain_dict, name="updated", entity_id="existing-id"
        )
        assert ref.version_id == "ver-2"

    @respx.mock
    def test_save_step(self, client, sample_step_dict):
        resp = {
            "entity_type": "step",
            "entity_id": "new-step-id",
            "version_id": "ver-1",
            "channel": "latest",
            "etag": "abc",
            "meta": {"name": "step"},
            "content": sample_step_dict,
        }
        respx.post("http://test-api:8000/v1/steps").mock(
            return_value=httpx.Response(201, json=resp)
        )
        ref = client.save_step(sample_step_dict, name="step")
        assert ref.entity_id == "new-step-id"
        assert ref.entity_type == "step"

    @respx.mock
    def test_update_step(self, client, sample_step_dict):
        resp = {
            "entity_type": "step",
            "entity_id": "existing-step-id",
            "version_id": "ver-2",
            "channel": "latest",
            "etag": "def",
            "meta": {"name": "step-updated"},
            "content": sample_step_dict,
        }
        respx.put("http://test-api:8000/v1/steps/existing-step-id").mock(
            return_value=httpx.Response(200, json=resp)
        )
        ref = client.save_step(
            sample_step_dict, name="step-updated", entity_id="existing-step-id"
        )
        assert ref.entity_id == "existing-step-id"
        assert ref.version_id == "ver-2"


class TestFacets:
    @respx.mock
    def test_get_facets(self, client):
        resp = {
            "entity_types": {"memory_card": 3},
            "tags": {"finance": 2},
            "authors": {"alice": 1},
            "namespaces": {"test": 4},
        }
        respx.get("http://test-api:8000/v1/search/facets").mock(
            return_value=httpx.Response(200, json=resp)
        )
        result = client.get_facets()
        assert result.entity_types["memory_card"] == 3
        assert result.tags["finance"] == 2


class TestVersioning:
    @respx.mock
    def test_list_versions(self, client, sample_version_info):
        respx.get(
            "http://test-api:8000/v1/chains/550e8400-e29b-41d4-a716-446655440000/versions"
        ).mock(return_value=httpx.Response(200, json=[sample_version_info]))
        versions = client.list_versions(
            "550e8400-e29b-41d4-a716-446655440000", entity_type="chain"
        )
        assert len(versions) == 1
        assert versions[0].author == "alice"


class TestCaching:
    @respx.mock
    def test_cache_hit_avoids_request(self, client, sample_entity_response):
        route = respx.get("http://test-api:8000/v1/chains/cached-id").mock(
            return_value=httpx.Response(200, json=sample_entity_response)
        )
        # First call: cache miss
        client.get_chain_dict("cached-id")
        assert route.call_count == 1

        # Second call: cache hit, no new request
        client.get_chain_dict("cached-id")
        assert route.call_count == 1

    @respx.mock
    def test_force_refresh_bypasses_cache(self, client, sample_entity_response):
        route = respx.get("http://test-api:8000/v1/chains/cached-id").mock(
            return_value=httpx.Response(200, json=sample_entity_response)
        )
        client.get_chain_dict("cached-id")
        client.get_chain_dict("cached-id", force_refresh=True)
        assert route.call_count == 2
