"""Tests for `POST /v1/bulk/save` (P2 §8)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.requests import BulkSaveItem
from app.routers.bulk import _save_one


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def _stub_db():
    async def _override():
        yield AsyncMock()
    return _override


def _entity_with_version():
    """Build a (entity, version) tuple that `_save_one` can return on success."""
    entity = MagicMock()
    entity.entity_id = uuid.uuid4()
    entity.entity_type = "chain"
    version = MagicMock()
    version.version_id = uuid.uuid4()
    return entity, version


def _bulk_item(entity_type: str = "chain", *, entity_id: str | None = None) -> dict:
    return {
        "entity_type": entity_type,
        "meta": {"name": f"{entity_type}-x"},
        "content": {"version": "1.1", "steps": [{"number": 1}],
                    "max_workers": 1, "metadata": {},
                    "search_config": {"strategy": "substring"}},
        "channel": "latest",
        "entity_id": entity_id,
    }


# ---------------------------------------------------------------------------
# _save_one — per-item logic
# ---------------------------------------------------------------------------


class TestSaveOne:
    @pytest.mark.asyncio
    async def test_create_path_returns_entity_ref(self):
        svc = AsyncMock()
        svc.create_entity = AsyncMock(return_value=_entity_with_version())
        item = BulkSaveItem(**_bulk_item("chain"))

        ok, ref, err = await _save_one(svc, item)

        assert ok is True
        assert err is None
        assert ref is not None
        assert ref["entity_type"] == "chain"
        assert "entity_id" in ref and "version_id" in ref
        svc.create_entity.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_path_uses_entity_id(self):
        svc = AsyncMock()
        svc.update_entity = AsyncMock(return_value=_entity_with_version())
        existing_id = str(uuid.uuid4())
        item = BulkSaveItem(**_bulk_item("chain", entity_id=existing_id))

        ok, ref, err = await _save_one(svc, item)

        assert ok is True
        assert err is None
        svc.update_entity.assert_awaited_once()
        kwargs = svc.update_entity.await_args.kwargs
        assert str(kwargs["entity_id"]) == existing_id

    @pytest.mark.asyncio
    async def test_unknown_entity_type_rejects_without_db_hit(self):
        svc = AsyncMock()
        svc.create_entity = AsyncMock(return_value=_entity_with_version())
        item = BulkSaveItem(**_bulk_item("BOGUS"))

        ok, ref, err = await _save_one(svc, item)

        assert ok is False
        assert ref is None
        assert "Invalid entity_type" in err
        svc.create_entity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_404_returns_failure_not_exception(self):
        svc = AsyncMock()
        svc.update_entity = AsyncMock(return_value=None)
        item = BulkSaveItem(**_bulk_item("chain", entity_id=str(uuid.uuid4())))

        ok, ref, err = await _save_one(svc, item)

        assert ok is False
        assert ref is None
        assert "not found" in err.lower()

    @pytest.mark.asyncio
    async def test_value_error_caught_as_per_item_failure(self):
        svc = AsyncMock()
        svc.create_entity = AsyncMock(side_effect=ValueError("malformed content"))
        item = BulkSaveItem(**_bulk_item("chain"))

        ok, ref, err = await _save_one(svc, item)

        assert ok is False
        assert ref is None
        assert "malformed content" in err


# ---------------------------------------------------------------------------
# End-to-end via TestClient
# ---------------------------------------------------------------------------


class TestBulkSaveEndpoint:
    """Route the request through FastAPI, mocking the service layer."""

    def test_three_creates_succeed(self, client):
        """Happy path: 3 items, all created."""
        app.dependency_overrides[get_db] = _stub_db()
        with patch(
            "app.routers.bulk._save_one",
            new=AsyncMock(side_effect=[
                (True, {"entity_type": "chain", "entity_id": "ch-1",
                        "version_id": "v1", "channel": "latest"}, None),
                (True, {"entity_type": "agent", "entity_id": "ag-1",
                        "version_id": "v1", "channel": "latest"}, None),
                (True, {"entity_type": "agent_skill", "entity_id": "sk-1",
                        "version_id": "v1", "channel": "latest"}, None),
            ]),
        ):
            resp = client.post("/v1/bulk/save", json={
                "items": [
                    _bulk_item("chain"),
                    _bulk_item("agent"),
                    _bulk_item("agent_skill"),
                ]
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success_count"] == 3
        assert body["error_count"] == 0
        assert len(body["results"]) == 3
        # Index ordering preserved.
        assert [r["index"] for r in body["results"]] == [0, 1, 2]
        # entity_refs present on each.
        assert all(r["entity_ref"] is not None for r in body["results"])

    def test_partial_failure_isolated_to_per_item(self, client):
        """Default `stop_on_error=False`: failure at index 1 doesn't
        skip index 2."""
        app.dependency_overrides[get_db] = _stub_db()
        with patch(
            "app.routers.bulk._save_one",
            new=AsyncMock(side_effect=[
                (True, {"entity_type": "chain", "entity_id": "ch-1",
                        "version_id": "v1", "channel": "latest"}, None),
                (False, None, "malformed content"),
                (True, {"entity_type": "agent_skill", "entity_id": "sk-1",
                        "version_id": "v1", "channel": "latest"}, None),
            ]),
        ):
            resp = client.post("/v1/bulk/save", json={
                "items": [_bulk_item("chain"), _bulk_item("chain"),
                          _bulk_item("agent_skill")],
            })
        body = resp.json()
        assert body["success_count"] == 2
        assert body["error_count"] == 1
        assert body["results"][1]["success"] is False
        assert body["results"][1]["error"] == "malformed content"
        assert body["results"][2]["success"] is True

    def test_stop_on_error_aborts_after_first_failure(self, client):
        """`stop_on_error=True`: index 2 should NEVER be tried."""
        app.dependency_overrides[get_db] = _stub_db()
        save_calls = []

        async def _spy_save(svc, item):
            save_calls.append(item.entity_type)
            if len(save_calls) == 1:
                return (True, {"entity_type": "chain", "entity_id": "x",
                               "version_id": "v", "channel": "latest"}, None)
            return (False, None, "boom")

        with patch("app.routers.bulk._save_one", new=_spy_save):
            resp = client.post("/v1/bulk/save", json={
                "items": [_bulk_item("chain"), _bulk_item("chain"), _bulk_item("chain")],
                "stop_on_error": True,
            })
        body = resp.json()
        assert len(save_calls) == 2  # third never attempted
        assert body["success_count"] == 1
        assert body["error_count"] == 1
        # Only 2 results because we stopped after the 2nd item.
        assert len(body["results"]) == 2

    def test_empty_items_rejected(self, client):
        """min_length=1 → 422 from Pydantic."""
        resp = client.post("/v1/bulk/save", json={"items": []})
        assert resp.status_code == 422

    def test_too_many_items_rejected(self, client):
        """max_length=500."""
        big = {"items": [_bulk_item("chain") for _ in range(501)]}
        resp = client.post("/v1/bulk/save", json=big)
        assert resp.status_code == 422


class TestRouterRegistration:
    def test_openapi_describes_bulk_save(self):
        schema = app.openapi()
        assert "/v1/bulk/save" in schema["paths"]
        assert "post" in schema["paths"]["/v1/bulk/save"]
        components = schema["components"]["schemas"]
        assert "BulkSaveRequest" in components
        assert "BulkSaveResponse" in components
        assert "BulkSaveItem" in components
        assert "BulkSaveItemResult" in components
