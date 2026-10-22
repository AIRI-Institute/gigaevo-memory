"""Tests for cursor pagination response headers on typed list endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def _bind_db():
    async def _override():
        yield AsyncMock()
    app.dependency_overrides[get_db] = _override


def _patch_list_entities(items=None, next_cursor=None, has_more=False):
    """Make ``EntityService.list_entities`` return a canned tuple
    regardless of args."""
    async def _fake(*_args, **_kwargs):
        return (items or []), next_cursor, has_more
    from app.services.entity_service import EntityService
    return patch.object(EntityService, "list_entities", new=_fake)


class TestCursorHeadersChains:
    def test_no_more_emits_false_no_cursor(self, client, _bind_db):
        with _patch_list_entities(has_more=False):
            resp = client.get("/v1/chains?limit=10")
        assert resp.status_code == 200
        assert resp.headers["X-Has-More"] == "false"
        assert "X-Next-Cursor" not in resp.headers

    def test_has_more_emits_true_with_cursor(self, client, _bind_db):
        with _patch_list_entities(next_cursor="ABCD", has_more=True):
            resp = client.get("/v1/chains?limit=10")
        assert resp.headers["X-Has-More"] == "true"
        assert resp.headers["X-Next-Cursor"] == "ABCD"

    def test_cursor_query_param_forwarded_to_service(self, client, _bind_db):
        captured: dict = {}

        async def _spy(self, *args, **kw):
            captured.update(kw)
            return [], None, False

        from app.services.entity_service import EntityService
        with patch.object(EntityService, "list_entities", new=_spy):
            client.get("/v1/chains?cursor=ABC")
        assert captured.get("cursor") == "ABC"

    def test_list_response_items_include_version_number(self, client, _bind_db):
        entity = MagicMock()
        entity.entity_id = uuid.uuid4()
        entity.favourite = False
        entity.run_count = 0
        entity.last_run_at = None
        entity.display_name = "chain"
        entity.description = None
        version = MagicMock()
        version.version_id = uuid.uuid4()
        version.version_number = 4
        version.meta_json = {"name": "chain"}
        version.content_json = {"version": "1.1", "steps": []}

        with _patch_list_entities(items=[(entity, version)]):
            resp = client.get("/v1/chains?limit=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"][0]["version_number"] == 4


class TestCursorHeadersAgents:
    def test_response_carries_headers(self, client, _bind_db):
        with _patch_list_entities(next_cursor="EFGH", has_more=True):
            resp = client.get("/v1/agents?limit=10")
        assert resp.headers["X-Has-More"] == "true"
        assert resp.headers["X-Next-Cursor"] == "EFGH"

    def test_cursor_forwarded(self, client, _bind_db):
        captured: dict = {}

        async def _spy(self, *args, **kw):
            captured.update(kw)
            return [], None, False

        from app.services.entity_service import EntityService
        with patch.object(EntityService, "list_entities", new=_spy):
            client.get("/v1/agents?cursor=AGENTS-X")
        assert captured.get("cursor") == "AGENTS-X"


class TestCursorHeadersAgentSkills:
    def test_response_carries_headers(self, client, _bind_db):
        with _patch_list_entities(next_cursor="IJKL", has_more=True):
            resp = client.get("/v1/agent-skills?limit=10")
        assert resp.headers["X-Has-More"] == "true"
        assert resp.headers["X-Next-Cursor"] == "IJKL"

    def test_cursor_invalidated_when_tool_filter_active(self, client, _bind_db):
        """Tool post-filter may drop the last-row → can't reuse cursor."""
        with _patch_list_entities(next_cursor="WOULD-BE-CURSOR", has_more=True):
            resp = client.get(
                "/v1/agent-skills?limit=10&excludes_tool=Bash"
            )
        # Server explicitly suppresses the cursor under tool filters.
        assert resp.headers["X-Has-More"] == "false"
        assert "X-Next-Cursor" not in resp.headers


class TestMemoryCardKindFilter:
    def test_dataset_kind_is_forwarded_and_cursor_is_preserved(self, client, _bind_db):
        captured: dict = {}

        def _pair(content: dict):
            entity = MagicMock()
            entity.entity_id = uuid.uuid4()
            version = MagicMock()
            version.version_id = uuid.uuid4()
            version.version_number = 2
            version.meta_json = {"name": content.get("name", "card")}
            version.content_json = content
            return entity, version

        async def _fake(self, *args, **kwargs):
            captured.update(kwargs)
            return [
                _pair({"kind": "dataset", "name": "Eval set", "rows": []}),
            ], "NEXT", True

        from app.services.entity_service import EntityService

        with patch.object(EntityService, "list_entities", new=_fake):
            resp = client.get("/v1/memory-cards?kind=dataset&limit=10")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["content"]["kind"] == "dataset"
        assert body["items"][0]["version_number"] == 2
        assert body["next_cursor"] == "NEXT"
        assert body["has_more"] is True
        assert resp.headers["X-Has-More"] == "true"
        assert resp.headers["X-Next-Cursor"] == "NEXT"
        assert captured["limit"] == 10
        assert captured["content_kind"] == "dataset"


class TestOpenAPI:
    def test_cursor_param_exposed(self, client):
        spec = app.openapi()
        for path in ("/v1/chains", "/v1/agents", "/v1/agent-skills"):
            params = {
                p["name"]: p for p in spec["paths"][path]["get"]["parameters"]
            }
            assert "cursor" in params, f"Missing cursor on {path}"
