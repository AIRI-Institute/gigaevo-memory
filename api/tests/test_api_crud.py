"""Integration tests for entity CRUD operations.

These tests require a running PostgreSQL and Redis, or use the FastAPI TestClient
with an in-memory/mock database setup.

NOTE: These tests are designed to be run against the full Docker stack via `make test`.
They serve as documentation of the expected API behavior and can be adapted to use
test doubles when running without infrastructure.
"""

import pytest


@pytest.mark.integration
class TestEntityCRUD:
    """Tests for POST/GET/PUT/DELETE /v1/{type}/{id}."""

    async def test_create_chain(self, async_client, create_chain_body):
        """POST /v1/chains creates a chain and returns 201."""
        resp = await async_client.post("/v1/chains", json=create_chain_body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["entity_type"] == "chain"
        assert "entity_id" in data
        assert "version_id" in data
        assert data["channel"] == "latest"
        assert data["content"]["version"] == "1.1"
        assert len(data["content"]["steps"]) == 2

    async def test_get_chain(self, async_client, create_chain_body):
        """POST then GET returns the same content."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]

        get_resp = await async_client.get(f"/v1/chains/{entity_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["content"] == create_chain_body["content"]

    async def test_get_nonexistent_returns_404(self, async_client):
        """GET with fake UUID returns 404."""
        resp = await async_client.get(
            "/v1/chains/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404

    async def test_update_creates_new_version(self, async_client, create_chain_body):
        """PUT creates a new version; version_id changes."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]
        v1_id = create_resp.json()["version_id"]

        # Update with modified content
        update_body = dict(create_chain_body)
        update_body["content"]["metadata"]["name"] = "updated_chain"
        update_resp = await async_client.put(
            f"/v1/chains/{entity_id}", json=update_body
        )
        assert update_resp.status_code == 200
        v2_id = update_resp.json()["version_id"]
        assert v2_id != v1_id

    async def test_soft_delete(self, async_client, create_chain_body):
        """DELETE sets deleted_at; subsequent GET returns 404."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]

        del_resp = await async_client.delete(f"/v1/chains/{entity_id}")
        assert del_resp.status_code == 204

        get_resp = await async_client.get(f"/v1/chains/{entity_id}")
        assert get_resp.status_code == 404

    async def test_etag_conditional_get(self, async_client, create_chain_body):
        """GET with matching If-None-Match returns 304."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]
        etag = create_resp.json()["etag"]

        get_resp = await async_client.get(
            f"/v1/chains/{entity_id}",
            headers={"If-None-Match": etag},
        )
        assert get_resp.status_code == 304

    async def test_invalid_entity_type(self, async_client, create_chain_body):
        """POST to invalid entity type returns 400."""
        resp = await async_client.post("/v1/invalid_type", json=create_chain_body)
        assert resp.status_code == 400


@pytest.mark.integration
class TestAllEntityTypes:
    """Verify CRUD works for all four entity types."""

    async def test_create_step(self, async_client):
        body = {
            "meta": {"name": "test_step", "tags": ["test"]},
            "channel": "latest",
            "content": {
                "number": 1,
                "title": "Test Step",
                "step_type": "llm",
                "aim": "Test purpose",
            },
        }
        resp = await async_client.post("/v1/steps", json=body)
        assert resp.status_code == 201
        assert resp.json()["entity_type"] == "step"

    async def test_create_agent(self, async_client):
        body = {
            "meta": {"name": "test_agent", "tags": ["test"]},
            "channel": "latest",
            "content": {
                "name": "test_agent",
                "description": "Test agent",
                "chain_ref": {
                    "entity_id": "00000000-0000-0000-0000-000000000001",
                    "entity_type": "chain",
                },
            },
        }
        resp = await async_client.post("/v1/agents", json=body)
        assert resp.status_code == 201
        assert resp.json()["entity_type"] == "agent"

    async def test_create_memory_card(self, async_client):
        body = {
            "meta": {"name": "test_memory_card", "tags": ["test"]},
            "channel": "latest",
            "content": {
                "id": "memory-card-test-123",
                "category": "testing",
                "task_description": "Test task description",
                "description": "A test memory card",
                "explanation": "Used in testing scenarios",
                "strategy": "exploration",
                "keywords": ["test", "example"],
                "evolution_statistics": {
                    "gain": 0.75,
                    "best_quartile": "Q1",
                    "survival": 5
                },
                "works_with": [],
                "links": [],
                "usage": {
                    "retrieved": 10,
                    "increased_fitness": 0.15
                }
            },
        }
        resp = await async_client.post("/v1/memory-cards", json=body)
        assert resp.status_code == 201
        assert resp.json()["entity_type"] == "memory_card"
