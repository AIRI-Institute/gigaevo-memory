"""Regression tests for version_number on generic EntityResponse routes."""

from __future__ import annotations

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


def _entity_version_pair(version_number: int = 5):
    entity = MagicMock()
    entity.entity_type = "agent_skill"
    entity.entity_id = uuid.uuid4()
    version = MagicMock()
    version.version_id = uuid.uuid4()
    version.version_number = version_number
    version.meta_json = {"name": "chain"}
    version.content_json = {"name": "skill", "description": "skill"}
    return entity, version


def test_generic_get_entity_includes_version_number(client, _bind_db):
    async def _fake_get(self, entity_id, channel):
        return _entity_version_pair(7)

    from app.services.entity_service import EntityService

    entity_id = uuid.uuid4()
    with patch.object(EntityService, "get_entity", new=_fake_get):
        resp = client.get(f"/v1/agent_skills/{entity_id}")

    assert resp.status_code == 200
    assert resp.json()["version_number"] == 7


def test_generic_create_entity_includes_version_number(client, _bind_db):
    async def _fake_create(self, **kwargs):
        return _entity_version_pair(0)

    from app.services.entity_service import EntityService

    with patch.object(EntityService, "create_entity", new=_fake_create):
        resp = client.post(
            "/v1/agent_skills",
            json={
                "meta": {"name": "skill"},
                "channel": "latest",
                "content": {"name": "skill", "description": "skill"},
            },
        )

    assert resp.status_code == 201
    assert resp.json()["version_number"] == 0


def test_generic_update_entity_includes_version_number(client, _bind_db):
    async def _fake_update(self, **kwargs):
        return _entity_version_pair(2)

    from app.services.entity_service import EntityService

    entity_id = uuid.uuid4()
    with patch.object(EntityService, "update_entity", new=_fake_update):
        resp = client.put(
            f"/v1/agent_skills/{entity_id}",
            json={
                "meta": {"name": "skill"},
                "channel": "latest",
                "content": {"name": "skill", "description": "skill"},
            },
        )

    assert resp.status_code == 200
    assert resp.json()["version_number"] == 2


def test_revert_includes_version_number(client, _bind_db):
    async def _fake_revert(self, entity_id, target_version_id):
        return _entity_version_pair(8)

    from app.services.entity_service import EntityService

    entity_id = uuid.uuid4()
    version_id = uuid.uuid4()
    with patch.object(EntityService, "revert", new=_fake_revert):
        resp = client.post(
            f"/v1/agent_skills/{entity_id}/revert",
            json={"target_version_id": str(version_id)},
        )

    assert resp.status_code == 200
    assert resp.json()["version_number"] == 8
