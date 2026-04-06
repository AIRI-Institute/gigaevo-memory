"""Integration tests for BYO vector search."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.config import settings


def _channel(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _body(create_chain_body: dict, *, name: str, embedding: list[float] | None) -> dict:
    body = deepcopy(create_chain_body)
    body["meta"]["name"] = name
    body["embedding"] = embedding
    return body


@pytest.fixture
def vector_search_enabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_vector_search", True)
    monkeypatch.setattr(settings, "vector_dimension", 3)


@pytest.mark.integration
class TestVectorSearch:
    async def test_vector_search_returns_channel_version(
        self,
        async_client,
        create_chain_body,
        vector_search_enabled,
    ):
        channel = _channel("vector-basic")
        create_body = _body(
            create_chain_body,
            name="vector-chain",
            embedding=[1.0, 0.0, 0.0],
        )
        create_body["channel"] = channel
        create_resp = await async_client.post(
            "/v1/chains",
            json=create_body,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()

        search_resp = await async_client.post(
            "/v1/search/vector",
            json={"query_vector": [1.0, 0.0, 0.0], "channel": channel, "limit": 5},
        )
        assert search_resp.status_code == 200
        data = search_resp.json()

        assert len(data["hits"]) == 1
        assert data["hits"][0]["entity_id"] == created["entity_id"]
        assert data["hits"][0]["version_id"] == created["version_id"]
        assert data["hits"][0]["channel"] == channel
        assert data["hits"][0]["score"] == pytest.approx(1.0)

    async def test_update_without_embedding_drops_latest_from_vector_search(
        self,
        async_client,
        create_chain_body,
        vector_search_enabled,
    ):
        channel = _channel("vector-drop")
        create_body = _body(
            create_chain_body,
            name="vector-chain",
            embedding=[1.0, 0.0, 0.0],
        )
        create_body["channel"] = channel
        create_resp = await async_client.post(
            "/v1/chains",
            json=create_body,
        )
        assert create_resp.status_code == 201
        entity_id = create_resp.json()["entity_id"]

        update_body = _body(create_chain_body, name="vector-chain-v2", embedding=None)
        update_body["channel"] = channel
        update_body["content"]["metadata"]["name"] = "vector-chain-v2"
        update_resp = await async_client.put(f"/v1/chains/{entity_id}", json=update_body)
        assert update_resp.status_code == 200

        search_resp = await async_client.post(
            "/v1/search/vector",
            json={"query_vector": [1.0, 0.0, 0.0], "channel": channel, "limit": 5},
        )
        assert search_resp.status_code == 200
        assert search_resp.json()["hits"] == []

    async def test_vector_search_respects_exact_channel(
        self,
        async_client,
        create_chain_body,
        vector_search_enabled,
    ):
        latest_channel = _channel("latest-vector")
        stable_channel = _channel("stable-vector")
        create_body = _body(
            create_chain_body,
            name="vector-chain",
            embedding=[1.0, 0.0, 0.0],
        )
        create_body["channel"] = latest_channel
        create_resp = await async_client.post("/v1/chains", json=create_body)
        assert create_resp.status_code == 201
        entity_id = create_resp.json()["entity_id"]
        version_v1 = create_resp.json()["version_id"]

        pin_resp = await async_client.post(
            f"/v1/chains/{entity_id}/pin",
            json={"channel": stable_channel, "version_id": version_v1},
        )
        assert pin_resp.status_code == 200

        update_body = _body(
            create_chain_body,
            name="vector-chain-v2",
            embedding=[0.0, 1.0, 0.0],
        )
        update_body["channel"] = latest_channel
        update_body["content"]["metadata"]["name"] = "vector-chain-v2"
        update_resp = await async_client.put(f"/v1/chains/{entity_id}", json=update_body)
        assert update_resp.status_code == 200
        version_v2 = update_resp.json()["version_id"]

        latest_resp = await async_client.post(
            "/v1/search/vector",
            json={
                "query_vector": [0.0, 1.0, 0.0],
                "channel": latest_channel,
                "limit": 5,
            },
        )
        stable_resp = await async_client.post(
            "/v1/search/vector",
            json={
                "query_vector": [1.0, 0.0, 0.0],
                "channel": stable_channel,
                "limit": 5,
            },
        )
        assert latest_resp.status_code == 200
        assert stable_resp.status_code == 200
        assert latest_resp.json()["hits"][0]["version_id"] == version_v2
        assert stable_resp.json()["hits"][0]["version_id"] == version_v1
        assert stable_resp.json()["hits"][0]["name"] == "vector-chain"

    async def test_vector_search_uses_version_metadata_for_pinned_channel(
        self,
        async_client,
        create_chain_body,
        vector_search_enabled,
    ):
        latest_channel = _channel("latest-meta")
        stable_channel = _channel("stable-meta")
        create_body = _body(
            create_chain_body,
            name="stable-name",
            embedding=[1.0, 0.0, 0.0],
        )
        create_body["channel"] = latest_channel
        create_body["meta"]["tags"] = ["stable-tag"]
        create_body["meta"]["when_to_use"] = "Stable metadata"
        create_resp = await async_client.post("/v1/chains", json=create_body)
        assert create_resp.status_code == 201
        entity_id = create_resp.json()["entity_id"]
        version_v1 = create_resp.json()["version_id"]

        pin_resp = await async_client.post(
            f"/v1/chains/{entity_id}/pin",
            json={"channel": stable_channel, "version_id": version_v1},
        )
        assert pin_resp.status_code == 200

        update_body = _body(
            create_chain_body,
            name="latest-name",
            embedding=[0.0, 1.0, 0.0],
        )
        update_body["channel"] = latest_channel
        update_body["meta"]["tags"] = ["latest-tag"]
        update_body["meta"]["when_to_use"] = "Latest metadata"
        update_body["content"]["metadata"]["name"] = "latest-name"
        update_resp = await async_client.put(f"/v1/chains/{entity_id}", json=update_body)
        assert update_resp.status_code == 200

        stable_resp = await async_client.post(
            "/v1/search/vector",
            json={
                "query_vector": [1.0, 0.0, 0.0],
                "channel": stable_channel,
                "limit": 5,
            },
        )
        assert stable_resp.status_code == 200
        stable_hit = stable_resp.json()["hits"][0]
        assert stable_hit["version_id"] == version_v1
        assert stable_hit["name"] == "stable-name"
        assert stable_hit["tags"] == ["stable-tag"]
        assert stable_hit["when_to_use"] == "Stable metadata"

        stable_tag_resp = await async_client.post(
            "/v1/search/vector",
            json={
                "query_vector": [1.0, 0.0, 0.0],
                "channel": stable_channel,
                "tags": ["stable-tag"],
                "limit": 5,
            },
        )
        latest_tag_resp = await async_client.post(
            "/v1/search/vector",
            json={
                "query_vector": [1.0, 0.0, 0.0],
                "channel": stable_channel,
                "tags": ["latest-tag"],
                "limit": 5,
            },
        )
        assert stable_tag_resp.status_code == 200
        assert latest_tag_resp.status_code == 200
        assert [hit["version_id"] for hit in stable_tag_resp.json()["hits"]] == [version_v1]
        assert latest_tag_resp.json()["hits"] == []

    async def test_revert_copies_embedding(
        self,
        async_client,
        create_chain_body,
        vector_search_enabled,
    ):
        namespace = _channel("revert-vector")
        create_body = _body(
            create_chain_body,
            name="vector-chain",
            embedding=[1.0, 0.0, 0.0],
        )
        create_body["meta"]["namespace"] = namespace
        create_body["meta"]["tags"] = ["v1-tag"]
        create_body["meta"]["when_to_use"] = "V1 metadata"
        create_resp = await async_client.post(
            "/v1/chains",
            json=create_body,
        )
        assert create_resp.status_code == 201
        entity_id = create_resp.json()["entity_id"]
        version_v1 = create_resp.json()["version_id"]

        update_body = _body(
            create_chain_body,
            name="vector-chain-v2",
            embedding=[0.0, 1.0, 0.0],
        )
        update_body["meta"]["namespace"] = namespace
        update_body["meta"]["tags"] = ["v2-tag"]
        update_body["meta"]["when_to_use"] = "V2 metadata"
        update_body["content"]["metadata"]["name"] = "vector-chain-v2"
        update_resp = await async_client.put(f"/v1/chains/{entity_id}", json=update_body)
        assert update_resp.status_code == 200

        revert_resp = await async_client.post(
            f"/v1/chains/{entity_id}/revert",
            json={"target_version_id": version_v1},
        )
        assert revert_resp.status_code == 200
        reverted_version = revert_resp.json()["version_id"]
        assert reverted_version != version_v1

        search_resp = await async_client.post(
            "/v1/search/vector",
            json={
                "query_vector": [1.0, 0.0, 0.0],
                "channel": "latest",
                "namespace": namespace,
                "limit": 5,
            },
        )
        assert search_resp.status_code == 200
        hit = search_resp.json()["hits"][0]
        assert hit["version_id"] == reverted_version
        assert hit["name"] == "vector-chain"
        assert hit["tags"] == ["v1-tag"]
        assert hit["when_to_use"] == "V1 metadata"

    async def test_vector_search_rejects_invalid_dimension(
        self,
        async_client,
        vector_search_enabled,
    ):
        search_resp = await async_client.post(
            "/v1/search/vector",
            json={"query_vector": [1.0, 0.0], "channel": "latest", "limit": 5},
        )
        assert search_resp.status_code == 400
        assert "exactly 3 dimensions" in search_resp.json()["detail"]

    async def test_create_rejects_invalid_embedding_dimension(
        self,
        async_client,
        create_chain_body,
        vector_search_enabled,
    ):
        create_resp = await async_client.post(
            "/v1/chains",
            json=_body(create_chain_body, name="bad-vector-chain", embedding=[1.0, 0.0]),
        )
        assert create_resp.status_code == 400
        assert "exactly 3 dimensions" in create_resp.json()["detail"]
