"""Integration tests for typed entity iteration endpoints."""

import base64
import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from app.db.models import Entity


def _make_channel(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _build_body(
    entity_type: str,
    *,
    name: str,
    channel: str,
    sample_chain_content: dict,
) -> dict:
    meta = {
        "name": name,
        "tags": ["iteration"],
        "when_to_use": "Integration testing",
        "author": "test_runner",
    }

    if entity_type == "step":
        content = {
            "number": 1,
            "title": "Iterated Step",
            "step_type": "llm",
            "aim": "Verify batched iteration",
        }
    elif entity_type == "chain":
        content = deepcopy(sample_chain_content)
        content["metadata"]["name"] = name
    elif entity_type == "agent":
        content = {
            "name": name,
            "description": "Iterated agent",
            "chain_ref": {
                "entity_id": str(uuid4()),
                "entity_type": "chain",
            },
        }
    elif entity_type == "memory_card":
        content = {
            "id": f"memory-card-{uuid4()}",
            "category": "testing",
            "task_description": "Verify batched iteration",
            "description": "Iterated memory card",
            "explanation": "Used by integration tests",
            "strategy": "exploration",
            "keywords": ["iteration"],
            "works_with": [],
            "links": [],
            "usage": {
                "retrieved": 1,
                "increased_fitness": 0.1,
            },
        }
    else:
        raise ValueError(f"Unsupported entity type: {entity_type}")

    return {
        "meta": meta,
        "channel": channel,
        "content": content,
    }


@pytest.mark.integration
class TestEntityIteration:
    @pytest.mark.parametrize(
        ("path", "entity_type"),
        [
            ("/v1/steps", "step"),
            ("/v1/chains", "chain"),
            ("/v1/agents", "agent"),
            ("/v1/memory-cards", "memory_card"),
        ],
    )
    async def test_list_endpoint_returns_requested_kind(
        self,
        async_client,
        sample_chain_content,
        path: str,
        entity_type: str,
    ):
        channel = _make_channel(f"{entity_type}-list")
        create_resp = await async_client.post(
            path,
            json=_build_body(
                entity_type,
                name=f"{entity_type}-iterated",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        assert create_resp.status_code == 201
        created = create_resp.json()

        list_resp = await async_client.get(path, params={"channel": channel, "limit": 100})
        assert list_resp.status_code == 200
        data = list_resp.json()

        assert data["has_more"] is False
        assert data["next_cursor"] is None
        assert len(data["items"]) == 1
        assert data["items"][0]["entity_type"] == entity_type
        assert data["items"][0]["entity_id"] == created["entity_id"]
        assert data["items"][0]["version_id"] == created["version_id"]
        assert data["items"][0]["channel"] == channel

    async def test_list_endpoint_filters_by_exact_channel(
        self,
        async_client,
        sample_chain_content,
    ):
        latest_channel = _make_channel("latest")
        stable_channel = _make_channel("stable")

        latest_resp = await async_client.post(
            "/v1/chains",
            json=_build_body(
                "chain",
                name="latest-chain",
                channel=latest_channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        stable_resp = await async_client.post(
            "/v1/chains",
            json=_build_body(
                "chain",
                name="stable-chain",
                channel=stable_channel,
                sample_chain_content=sample_chain_content,
            ),
        )

        latest_page = await async_client.get(
            "/v1/chains",
            params={"channel": latest_channel, "limit": 100},
        )
        stable_page = await async_client.get(
            "/v1/chains",
            params={"channel": stable_channel, "limit": 100},
        )

        assert latest_page.status_code == 200
        assert stable_page.status_code == 200
        assert [item["entity_id"] for item in latest_page.json()["items"]] == [
            latest_resp.json()["entity_id"]
        ]
        assert [item["entity_id"] for item in stable_page.json()["items"]] == [
            stable_resp.json()["entity_id"]
        ]

    async def test_list_endpoint_resolves_exact_channel_version(
        self,
        async_client,
        sample_chain_content,
    ):
        latest_channel = _make_channel("latest")
        stable_channel = _make_channel("stable")

        create_resp = await async_client.post(
            "/v1/chains",
            json=_build_body(
                "chain",
                name="multi-channel-chain",
                channel=latest_channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        assert create_resp.status_code == 201
        entity_id = create_resp.json()["entity_id"]
        version_v1 = create_resp.json()["version_id"]

        pin_resp = await async_client.post(
            f"/v1/chains/{entity_id}/pin",
            json={"channel": stable_channel, "version_id": version_v1},
        )
        assert pin_resp.status_code == 200

        update_body = _build_body(
            "chain",
            name="multi-channel-chain-v2",
            channel=latest_channel,
            sample_chain_content=sample_chain_content,
        )
        update_resp = await async_client.put(f"/v1/chains/{entity_id}", json=update_body)
        assert update_resp.status_code == 200
        version_v2 = update_resp.json()["version_id"]

        latest_only_resp = await async_client.post(
            "/v1/chains",
            json=_build_body(
                "chain",
                name="latest-only-chain",
                channel=latest_channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        assert latest_only_resp.status_code == 201

        latest_page = await async_client.get(
            "/v1/chains",
            params={"channel": latest_channel, "limit": 100},
        )
        stable_page = await async_client.get(
            "/v1/chains",
            params={"channel": stable_channel, "limit": 100},
        )

        assert latest_page.status_code == 200
        assert stable_page.status_code == 200

        latest_items = latest_page.json()["items"]
        stable_items = stable_page.json()["items"]

        latest_item_by_id = {item["entity_id"]: item for item in latest_items}
        stable_item_by_id = {item["entity_id"]: item for item in stable_items}

        assert latest_item_by_id[entity_id]["version_id"] == version_v2
        assert latest_item_by_id[entity_id]["channel"] == latest_channel
        assert latest_only_resp.json()["entity_id"] in latest_item_by_id
        assert all(item["channel"] == latest_channel for item in latest_items)

        assert list(stable_item_by_id) == [entity_id]
        assert stable_item_by_id[entity_id]["version_id"] == version_v1
        assert stable_item_by_id[entity_id]["channel"] == stable_channel
        assert latest_only_resp.json()["entity_id"] not in stable_item_by_id
        assert all(item["channel"] == stable_channel for item in stable_items)

    async def test_list_endpoint_paginates_without_duplicates(
        self,
        async_client,
        sample_chain_content,
    ):
        channel = _make_channel("memory-card-page")
        first_resp = await async_client.post(
            "/v1/memory-cards",
            json=_build_body(
                "memory_card",
                name="memory-card-a",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        second_resp = await async_client.post(
            "/v1/memory-cards",
            json=_build_body(
                "memory_card",
                name="memory-card-b",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )

        first_page = await async_client.get(
            "/v1/memory-cards",
            params={"channel": channel, "limit": 1},
        )
        assert first_page.status_code == 200
        first_data = first_page.json()
        assert len(first_data["items"]) == 1
        assert first_data["has_more"] is True
        assert first_data["next_cursor"] is not None

        second_page = await async_client.get(
            "/v1/memory-cards",
            params={
                "channel": channel,
                "limit": 1,
                "cursor": first_data["next_cursor"],
            },
        )
        assert second_page.status_code == 200
        second_data = second_page.json()
        assert len(second_data["items"]) == 1
        assert second_data["has_more"] is False
        assert second_data["next_cursor"] is None

        returned_ids = {
            first_data["items"][0]["entity_id"],
            second_data["items"][0]["entity_id"],
        }
        assert returned_ids == {
            first_resp.json()["entity_id"],
            second_resp.json()["entity_id"],
        }

    async def test_list_endpoint_orders_equal_timestamps_by_entity_id(
        self,
        async_client,
        db_session,
        sample_chain_content,
    ):
        channel = _make_channel("tie-order")
        first_resp = await async_client.post(
            "/v1/memory-cards",
            json=_build_body(
                "memory_card",
                name="memory-card-tie-a",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        second_resp = await async_client.post(
            "/v1/memory-cards",
            json=_build_body(
                "memory_card",
                name="memory-card-tie-b",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        assert first_resp.status_code == 201
        assert second_resp.status_code == 201

        entity_ids = [
            UUID(first_resp.json()["entity_id"]),
            UUID(second_resp.json()["entity_id"]),
        ]
        tied_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        await db_session.execute(
            update(Entity)
            .where(Entity.entity_id.in_(entity_ids))
            .values(created_at=tied_created_at)
        )
        await db_session.commit()

        expected_rows = await db_session.execute(
            select(Entity.entity_id)
            .where(
                Entity.entity_type == "memory_card",
                Entity.deleted_at.is_(None),
                Entity.channels.op("?")(channel),
            )
            .order_by(Entity.created_at.asc(), Entity.entity_id.asc())
        )
        expected_order = [str(entity_id) for entity_id in expected_rows.scalars().all()]
        assert expected_order == sorted(str(entity_id) for entity_id in entity_ids)

        first_page = await async_client.get(
            "/v1/memory-cards",
            params={"channel": channel, "limit": 1},
        )
        assert first_page.status_code == 200
        first_data = first_page.json()

        second_page = await async_client.get(
            "/v1/memory-cards",
            params={
                "channel": channel,
                "limit": 1,
                "cursor": first_data["next_cursor"],
            },
        )
        assert second_page.status_code == 200
        second_data = second_page.json()

        returned_order = [
            first_data["items"][0]["entity_id"],
            second_data["items"][0]["entity_id"],
        ]

        assert first_data["has_more"] is True
        assert first_data["next_cursor"] is not None
        assert second_data["has_more"] is False
        assert second_data["next_cursor"] is None
        assert returned_order == expected_order
        assert len(set(returned_order)) == 2

    async def test_list_endpoint_excludes_soft_deleted_entities(
        self,
        async_client,
        sample_chain_content,
    ):
        channel = _make_channel("deleted-memory-card")
        create_resp = await async_client.post(
            "/v1/memory-cards",
            json=_build_body(
                "memory_card",
                name="deleted-memory-card",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        entity_id = create_resp.json()["entity_id"]

        delete_resp = await async_client.delete(f"/v1/memory-cards/{entity_id}")
        assert delete_resp.status_code == 204

        list_resp = await async_client.get(
            "/v1/memory-cards",
            params={"channel": channel, "limit": 100},
        )
        assert list_resp.status_code == 200
        assert list_resp.json() == {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

    async def test_list_endpoint_requires_channel(self, async_client):
        resp = await async_client.get("/v1/steps", params={"limit": 10})
        assert resp.status_code == 422

    async def test_list_endpoint_rejects_malformed_cursor(
        self,
        async_client,
    ):
        resp = await async_client.get(
            "/v1/chains",
            params={"channel": _make_channel("malformed"), "cursor": "not-a-cursor"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid cursor"

    async def test_list_endpoint_rejects_empty_cursor(
        self,
        async_client,
    ):
        resp = await async_client.get(
            "/v1/chains",
            params={"channel": _make_channel("empty-cursor"), "cursor": ""},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid cursor"

    @pytest.mark.parametrize("payload", ["oops", ["oops"]])
    async def test_list_endpoint_rejects_non_object_cursor_payload(
        self,
        async_client,
        payload,
    ):
        cursor = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")

        resp = await async_client.get(
            "/v1/chains",
            params={"channel": _make_channel("payload-shape"), "cursor": cursor},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid cursor"

    async def test_list_endpoint_rejects_cursor_entity_type_mismatch(
        self,
        async_client,
        sample_chain_content,
    ):
        channel = _make_channel("cursor-type")
        await async_client.post(
            "/v1/chains",
            json=_build_body(
                "chain",
                name="chain-a",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        await async_client.post(
            "/v1/chains",
            json=_build_body(
                "chain",
                name="chain-b",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )

        page = await async_client.get(
            "/v1/chains",
            params={"channel": channel, "limit": 1},
        )
        cursor = page.json()["next_cursor"]

        mismatch_resp = await async_client.get(
            "/v1/steps",
            params={"channel": channel, "cursor": cursor},
        )
        assert mismatch_resp.status_code == 400
        assert mismatch_resp.json()["detail"] == "Cursor entity type mismatch"

    async def test_list_endpoint_rejects_cursor_channel_mismatch(
        self,
        async_client,
        sample_chain_content,
    ):
        channel = _make_channel("cursor-channel")
        await async_client.post(
            "/v1/agents",
            json=_build_body(
                "agent",
                name="agent-a",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )
        await async_client.post(
            "/v1/agents",
            json=_build_body(
                "agent",
                name="agent-b",
                channel=channel,
                sample_chain_content=sample_chain_content,
            ),
        )

        page = await async_client.get(
            "/v1/agents",
            params={"channel": channel, "limit": 1},
        )
        cursor = page.json()["next_cursor"]

        mismatch_resp = await async_client.get(
            "/v1/agents",
            params={"channel": _make_channel("other-channel"), "cursor": cursor},
        )
        assert mismatch_resp.status_code == 400
        assert mismatch_resp.json()["detail"] == "Cursor channel mismatch"
