"""Integration tests for version management endpoints."""

from copy import deepcopy

import pytest


@pytest.mark.integration
class TestVersionManagement:
    """Tests for version listing, diff, revert, pin, promote."""

    async def test_list_versions(self, async_client, create_chain_body):
        """GET /v1/chains/{id}/versions returns version list."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]

        # Create a second version
        update_body = deepcopy(create_chain_body)
        update_body["content"]["metadata"]["name"] = "v2"
        await async_client.put(f"/v1/chains/{entity_id}", json=update_body)

        resp = await async_client.get(f"/v1/chains/{entity_id}/versions")
        assert resp.status_code == 200
        versions = resp.json()
        assert len(versions) == 2
        # Newest first
        assert versions[0]["version_id"] != versions[1]["version_id"]

    async def test_get_specific_version(self, async_client, create_chain_body):
        """GET /v1/chains/{id}/versions/{ver_id} returns version detail."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]
        version_id = create_resp.json()["version_id"]

        resp = await async_client.get(
            f"/v1/chains/{entity_id}/versions/{version_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version_id"] == version_id
        assert "content" in data

    async def test_revert_creates_new_version(self, async_client, create_chain_body):
        """POST /v1/chains/{id}/revert creates a new version from old content."""
        # Create v1
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]
        v1_id = create_resp.json()["version_id"]
        original_content = deepcopy(create_chain_body["content"])

        # Create v2
        update_body = deepcopy(create_chain_body)
        update_body["content"]["metadata"]["name"] = "v2_modified"
        await async_client.put(f"/v1/chains/{entity_id}", json=update_body)

        # Revert to v1
        revert_resp = await async_client.post(
            f"/v1/chains/{entity_id}/revert",
            json={"target_version_id": v1_id},
        )
        assert revert_resp.status_code == 200
        # New version with v1's content
        v3_id = revert_resp.json()["version_id"]
        assert v3_id != v1_id  # It's a new version, not the same as v1
        assert revert_resp.json()["content"] == original_content

    async def test_content_only_update_inherits_channel_version_metadata(
        self, async_client, create_chain_body
    ):
        """Content-only updates preserve metadata from the channel-resolved parent version."""
        latest_channel = "latest-version-meta"
        stable_channel = "stable-version-meta"

        create_body = deepcopy(create_chain_body)
        create_body["channel"] = latest_channel
        create_body["meta"]["name"] = "stable-name"
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

        latest_update_body = deepcopy(create_chain_body)
        latest_update_body["channel"] = latest_channel
        latest_update_body["meta"]["name"] = "latest-name"
        latest_update_body["meta"]["tags"] = ["latest-tag"]
        latest_update_body["meta"]["when_to_use"] = "Latest metadata"
        latest_update_body["content"]["metadata"]["name"] = "latest-content"
        latest_update_resp = await async_client.put(
            f"/v1/chains/{entity_id}", json=latest_update_body
        )
        assert latest_update_resp.status_code == 200

        stable_update_body = {
            "channel": stable_channel,
            "content": deepcopy(create_chain_body["content"]),
        }
        stable_update_body["content"]["metadata"]["name"] = "stable-content-v2"
        stable_update_resp = await async_client.put(
            f"/v1/chains/{entity_id}", json=stable_update_body
        )
        assert stable_update_resp.status_code == 200
        assert stable_update_resp.json()["meta"]["name"] == "stable-name"
        assert stable_update_resp.json()["meta"]["tags"] == ["stable-tag"]
        assert (
            stable_update_resp.json()["meta"]["when_to_use"] == "Stable metadata"
        )

        stable_get_resp = await async_client.get(
            f"/v1/chains/{entity_id}",
            params={"channel": stable_channel},
        )
        assert stable_get_resp.status_code == 200
        assert stable_get_resp.json()["meta"]["name"] == "stable-name"
        assert stable_get_resp.json()["meta"]["tags"] == ["stable-tag"]
        assert stable_get_resp.json()["meta"]["when_to_use"] == "Stable metadata"

    async def test_revert_inherits_target_version_metadata(
        self, async_client, create_chain_body
    ):
        """Revert preserves metadata from the target version, not current entity metadata."""
        create_body = deepcopy(create_chain_body)
        create_body["meta"]["name"] = "v1-name"
        create_body["meta"]["tags"] = ["v1-tag"]
        create_body["meta"]["when_to_use"] = "V1 metadata"
        create_resp = await async_client.post("/v1/chains", json=create_body)
        assert create_resp.status_code == 201
        entity_id = create_resp.json()["entity_id"]
        version_v1 = create_resp.json()["version_id"]

        update_body = deepcopy(create_chain_body)
        update_body["meta"]["name"] = "v2-name"
        update_body["meta"]["tags"] = ["v2-tag"]
        update_body["meta"]["when_to_use"] = "V2 metadata"
        update_body["content"]["metadata"]["name"] = "v2-content"
        update_resp = await async_client.put(f"/v1/chains/{entity_id}", json=update_body)
        assert update_resp.status_code == 200

        revert_resp = await async_client.post(
            f"/v1/chains/{entity_id}/revert",
            json={"target_version_id": version_v1},
        )
        assert revert_resp.status_code == 200
        assert revert_resp.json()["meta"]["name"] == "v1-name"
        assert revert_resp.json()["meta"]["tags"] == ["v1-tag"]
        assert revert_resp.json()["meta"]["when_to_use"] == "V1 metadata"

    async def test_parent_version_id_does_not_override_channel_metadata_source(
        self, async_client, create_chain_body
    ):
        """parent_version_id affects lineage only; metadata still defaults from the channel version."""
        latest_channel = "latest-parent-meta"
        stable_channel = "stable-parent-meta"

        create_body = deepcopy(create_chain_body)
        create_body["channel"] = latest_channel
        create_body["meta"]["name"] = "stable-name"
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

        latest_update_body = deepcopy(create_chain_body)
        latest_update_body["channel"] = latest_channel
        latest_update_body["meta"]["name"] = "latest-name"
        latest_update_body["meta"]["tags"] = ["latest-tag"]
        latest_update_body["meta"]["when_to_use"] = "Latest metadata"
        latest_update_body["content"]["metadata"]["name"] = "latest-content"
        latest_update_resp = await async_client.put(
            f"/v1/chains/{entity_id}", json=latest_update_body
        )
        assert latest_update_resp.status_code == 200
        latest_version_id = latest_update_resp.json()["version_id"]

        stable_update_body = {
            "channel": stable_channel,
            "content": deepcopy(create_chain_body["content"]),
            "parent_version_id": latest_version_id,
        }
        stable_update_body["content"]["metadata"]["name"] = "stable-content-v2"
        stable_update_resp = await async_client.put(
            f"/v1/chains/{entity_id}", json=stable_update_body
        )
        assert stable_update_resp.status_code == 200
        assert stable_update_resp.json()["meta"]["name"] == "stable-name"
        assert stable_update_resp.json()["meta"]["tags"] == ["stable-tag"]
        assert (
            stable_update_resp.json()["meta"]["when_to_use"] == "Stable metadata"
        )

    async def test_pin_channel(self, async_client, create_chain_body):
        """POST /v1/chains/{id}/pin sets channel pointer."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]
        version_id = create_resp.json()["version_id"]

        resp = await async_client.post(
            f"/v1/chains/{entity_id}/pin",
            json={"channel": "stable", "version_id": version_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pinned"

    async def test_promote(self, async_client, create_chain_body):
        """POST /v1/chains/{id}/promote copies latest -> stable."""
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]

        resp = await async_client.post(f"/v1/chains/{entity_id}/promote")
        assert resp.status_code == 200
        assert resp.json()["status"] == "promoted"

    async def test_diff_versions(self, async_client, create_chain_body):
        """GET /v1/chains/{id}/diff returns JSON patch between versions."""
        # Create v1
        create_resp = await async_client.post("/v1/chains", json=create_chain_body)
        entity_id = create_resp.json()["entity_id"]
        v1_id = create_resp.json()["version_id"]

        # Create v2
        update_body = deepcopy(create_chain_body)
        update_body["content"]["metadata"]["name"] = "changed_name"
        update_resp = await async_client.put(
            f"/v1/chains/{entity_id}", json=update_body
        )
        v2_id = update_resp.json()["version_id"]

        resp = await async_client.get(
            f"/v1/chains/{entity_id}/diff",
            params={"from": v1_id, "to": v2_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_version"] == v1_id
        assert data["to_version"] == v2_id
        assert "patch" in data
