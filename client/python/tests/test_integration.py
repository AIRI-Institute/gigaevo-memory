"""Integration tests for MemoryClient workflows."""

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


class TestChainWorkflow:
    def test_full_chain_lifecycle(self, client):
        chain_content = {
            "version": "1.1",
            "max_workers": 3,
            "enable_progress": False,
            "metadata": {"name": "test_chain"},
            "search_config": {"strategy": "substring"},
            "steps": [
                {
                    "number": 1,
                    "title": "Step 1",
                    "dependencies": [],
                    "step_type": "llm",
                    "aim": "Test",
                    "reasoning_questions": "",
                    "step_context_queries": [],
                    "stage_action": "",
                    "example_reasoning": ""
                }
            ]
        }
        
        with respx.mock:
            create_response = {
                "entity_type": "chain",
                "entity_id": "chain-123",
                "version_id": "ver-1",
                "channel": "latest",
                "etag": "abc",
                "meta": {"name": "test_chain"},
                "content": chain_content
            }
            respx.post("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(201, json=create_response)
            )
            
            ref = client.save_chain(chain_content, name="test_chain")
            assert ref.entity_id == "chain-123"


class TestHealthCheck:
    def test_health_check_success(self, client):
        with respx.mock:
            respx.get("http://test-api:8000/health").mock(
                return_value=httpx.Response(200, json={"status": "ok", "postgres": "ok", "redis": "ok"})
            )
            health = client.health_check()
            assert health["status"] == "ok"


class TestClearAll:
    def test_clear_all(self, client):
        with respx.mock:
            respx.post("http://test-api:8000/v1/maintenance/clear-all").mock(
                return_value=httpx.Response(200, json={"chain": 5, "agent": 3})
            )
            result = client.clear_all()
            assert result["chain"] == 5
