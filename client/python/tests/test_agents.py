"""Tests for agent operations in MemoryClient."""

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient, NotFoundError
from gigaevo_memory.models import AgentSpec, EntityRef


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


@pytest.fixture
def sample_agent_spec():
    return AgentSpec(
        name="test_agent",
        description="Test agent description",
        chain_ref={
            "entity_id": "550e8400-e29b-41d4-a716-446655440000",
            "entity_type": "chain",
            "channel": "latest"
        },
        system_prompt="You are a helpful assistant.",
        default_model="gpt-4o",
        max_workers=3,
        tool_manifests=[],
        tags=["test", "agent"],
        when_to_use="For testing purposes"
    )


class TestGetAgent:
    def test_get_agent_success(self, client, sample_agent_spec):
        response = {
            "entity_type": "agent",
            "entity_id": "agent-id-123",
            "version_id": "ver-456",
            "channel": "latest",
            "etag": "abc123",
            "meta": {"name": "test_agent"},
            "content": sample_agent_spec.model_dump(mode="json")
        }
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/agents/agent-id-123").mock(
                return_value=httpx.Response(200, json=response)
            )
            agent = client.get_agent("agent-id-123")
        
        assert isinstance(agent, AgentSpec)
        assert agent.name == "test_agent"

    def test_get_agent_not_found(self, client):
        with respx.mock:
            respx.get("http://test-api:8000/v1/agents/missing-id").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"})
            )
            with pytest.raises(NotFoundError):
                client.get_agent("missing-id")


class TestSaveAgent:
    def test_save_agent_create(self, client, sample_agent_spec):
        response = {
            "entity_type": "agent",
            "entity_id": "new-agent-id",
            "version_id": "ver-1",
            "channel": "latest",
            "etag": "abc",
            "meta": {"name": "test_agent"},
            "content": sample_agent_spec.model_dump(mode="json")
        }
        
        with respx.mock:
            respx.post("http://test-api:8000/v1/agents").mock(
                return_value=httpx.Response(201, json=response)
            )
            ref = client.save_agent(
                sample_agent_spec,
                name="test_agent",
                tags=["test"]
            )
        
        assert isinstance(ref, EntityRef)
        assert ref.entity_id == "new-agent-id"
        assert ref.entity_type == "agent"

    def test_save_agent_update(self, client, sample_agent_spec):
        response = {
            "entity_type": "agent",
            "entity_id": "existing-agent-id",
            "version_id": "ver-2",
            "channel": "latest",
            "etag": "def",
            "meta": {"name": "updated_agent"},
            "content": sample_agent_spec.model_dump(mode="json")
        }
        
        with respx.mock:
            respx.put("http://test-api:8000/v1/agents/existing-agent-id").mock(
                return_value=httpx.Response(200, json=response)
            )
            ref = client.save_agent(
                sample_agent_spec,
                name="updated_agent",
                entity_id="existing-agent-id"
            )
        
        assert ref.entity_id == "existing-agent-id"
        assert ref.version_id == "ver-2"


class TestListAgents:
    def test_list_agents_success(self, client):
        response = [
            {
                "entity_type": "agent",
                "entity_id": "agent-1",
                "version_id": "ver-1",
                "channel": "latest",
                "etag": "abc",
                "meta": {"name": "Agent 1"},
                "content": {"name": "Agent 1"}
            },
            {
                "entity_type": "agent",
                "entity_id": "agent-2",
                "version_id": "ver-1",
                "channel": "latest",
                "etag": "def",
                "meta": {"name": "Agent 2"},
                "content": {"name": "Agent 2"}
            }
        ]
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/agents").mock(
                return_value=httpx.Response(200, json=response)
            )
            agents = client.list_agents(limit=10)
        
        assert len(agents) == 2
        assert agents[0].entity_id == "agent-1"
        assert agents[1].entity_id == "agent-2"


class TestDeleteAgent:
    def test_delete_agent_success(self, client):
        with respx.mock:
            respx.delete("http://test-api:8000/v1/agents/agent-id-123").mock(
                return_value=httpx.Response(204)
            )
            result = client.delete_agent("agent-id-123")
        
        assert result is True

    def test_delete_agent_not_found(self, client):
        with respx.mock:
            respx.delete("http://test-api:8000/v1/agents/missing-id").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"})
            )
            with pytest.raises(NotFoundError):
                client.delete_agent("missing-id")
