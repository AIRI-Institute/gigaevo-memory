"""Tests for ``MemoryClient.bulk_save`` (P2 §8)."""

import json

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


def _item(entity_type: str = "chain", **ov) -> dict:
    base = {
        "entity_type": entity_type,
        "meta": {"name": f"{entity_type}-x"},
        "content": {"version": "1.1", "steps": [{"number": 1}]},
        "channel": "latest",
    }
    base.update(ov)
    return base


class TestBulkSaveRequestBody:
    def test_posts_items_and_default_stop_on_error_false(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/bulk/save").mock(
                return_value=httpx.Response(200, json={
                    "results": [
                        {"index": 0, "success": True, "entity_ref": {
                            "entity_type": "chain", "entity_id": "ch-1",
                            "version_id": "v1", "channel": "latest",
                        }, "error": None},
                    ],
                    "success_count": 1, "error_count": 0,
                })
            )
            client.bulk_save([_item("chain")])
        body = json.loads(route.calls.last.request.content)
        assert body == {
            "items": [_item("chain")],
            "stop_on_error": False,
        }

    def test_stop_on_error_true_passed_through(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/bulk/save").mock(
                return_value=httpx.Response(200, json={
                    "results": [], "success_count": 0, "error_count": 0,
                })
            )
            client.bulk_save([_item()], stop_on_error=True)
        body = json.loads(route.calls.last.request.content)
        assert body["stop_on_error"] is True

    def test_empty_items_short_circuits_before_network(self, client):
        """Server enforces min_length=1; we avoid the 422 round-trip."""
        with respx.mock(assert_all_called=False) as mock:
            mock.post("http://test-api:8000/v1/bulk/save").mock(
                return_value=httpx.Response(200, json={})
            )
            out = client.bulk_save([])
            assert out == {"results": [], "success_count": 0, "error_count": 0}
            assert len(mock.calls) == 0


class TestBulkSaveResponseShape:
    def test_returns_full_response_envelope(self, client):
        with respx.mock:
            respx.post("http://test-api:8000/v1/bulk/save").mock(
                return_value=httpx.Response(200, json={
                    "results": [
                        {"index": 0, "success": True, "entity_ref": {
                            "entity_type": "chain", "entity_id": "ch-1",
                            "version_id": "v1", "channel": "latest",
                        }, "error": None},
                        {"index": 1, "success": False, "entity_ref": None,
                         "error": "malformed content"},
                    ],
                    "success_count": 1, "error_count": 1,
                })
            )
            out = client.bulk_save([_item(), _item()])
        assert out["success_count"] == 1
        assert out["error_count"] == 1
        assert len(out["results"]) == 2
        # Per-item error message preserved.
        assert out["results"][1]["error"] == "malformed content"
        # Success rows carry an entity_ref payload usable for follow-ups.
        assert out["results"][0]["entity_ref"]["entity_id"] == "ch-1"

    def test_mixed_entity_types_in_one_call(self, client):
        """The bulk endpoint accepts mixed types — CARE's import flow."""
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/bulk/save").mock(
                return_value=httpx.Response(200, json={
                    "results": [
                        {"index": i, "success": True, "entity_ref": {
                            "entity_type": t, "entity_id": f"x{i}",
                            "version_id": "v", "channel": "latest",
                        }, "error": None}
                        for i, t in enumerate(["chain", "agent", "agent_skill"])
                    ],
                    "success_count": 3, "error_count": 0,
                })
            )
            out = client.bulk_save([
                _item("chain"), _item("agent"), _item("agent_skill"),
            ])
        assert out["success_count"] == 3
        # All three types present in the per-item refs.
        types = [r["entity_ref"]["entity_type"] for r in out["results"]]
        assert types == ["chain", "agent", "agent_skill"]

        # Verify the wire body carried all three.
        body = json.loads(route.calls.last.request.content)
        assert [it["entity_type"] for it in body["items"]] == [
            "chain", "agent", "agent_skill",
        ]


class TestBulkSaveUpsertMode:
    def test_entity_id_serialised_when_set(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/bulk/save").mock(
                return_value=httpx.Response(200, json={
                    "results": [{
                        "index": 0, "success": True, "entity_ref": {
                            "entity_type": "chain", "entity_id": "existing",
                            "version_id": "v2", "channel": "latest",
                        }, "error": None,
                    }],
                    "success_count": 1, "error_count": 0,
                })
            )
            client.bulk_save([_item("chain", entity_id="existing")])
        body = json.loads(route.calls.last.request.content)
        assert body["items"][0]["entity_id"] == "existing"
