"""Tests for auth + namespace defaulting on the agents router
(P1 §3 follow-up — iteration #31). Mirrors the chains test layout
so future router rollouts can be diffed at a glance."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.models import ApiKey
from app.db.session import get_db
from app.main import app
from app.services.api_key_service import _hash_key


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _opt_in(monkeypatch):
    """Default mode for these tests: opt-in (matches deployment default)."""
    from app import auth as auth_mod
    monkeypatch.setattr(auth_mod.settings, "auth_required", False)


def _stub_db_for_auth(row: ApiKey | None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override


def _agent_body(*, namespace: str | None = None) -> dict:
    body: dict = {
        "meta": {"name": "researcher"},
        "content": {
            "version": "1.0",
            "system_prompt": "You are a researcher.",
            "tools": [],
        },
        "channel": "latest",
    }
    if namespace is not None:
        body["meta"]["namespace"] = namespace
    return body


@pytest.fixture
def _capture_create():
    """Capture the `namespace=` kwarg passed into the service's
    create_entity so we can assert on it."""
    captured: dict = {}

    async def _spy(self, **kw):
        captured.update(kw)
        entity = MagicMock()
        entity.entity_id = uuid.uuid4()
        entity.entity_type = "agent"
        entity.favourite = False
        entity.run_count = 0
        entity.last_run_at = None
        entity.display_name = "researcher"
        entity.description = None
        version = MagicMock()
        version.version_id = uuid.uuid4()
        version.content_json = kw["content"]
        version.meta_json = {}
        return entity, version

    from app.services.entity_service import EntityService

    with patch.object(EntityService, "create_entity", new=_spy):
        yield captured


class TestAgentsCreateOptIn:
    def test_no_key_namespace_stays_none(self, client, _capture_create):
        _stub_db_for_auth(None)
        resp = client.post("/v1/agents", json=_agent_body())
        assert resp.status_code == 201
        assert _capture_create["namespace"] is None

    def test_no_key_explicit_namespace_respected(self, client, _capture_create):
        _stub_db_for_auth(None)
        resp = client.post("/v1/agents", json=_agent_body(namespace="shared"))
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "shared"


class TestAgentsCreateAuthenticated:
    def _row(self, plaintext: str, owner: str = "glazkov") -> ApiKey:
        return ApiKey(
            key_id=uuid.uuid4(),
            key_hash=_hash_key(plaintext),
            owner=owner, label=None,
            scopes=[], created_at=datetime.now(timezone.utc),
            expires_at=None, revoked_at=None,
        )

    def test_valid_key_defaults_to_owner(self, client, _capture_create):
        plaintext = "valid-token"
        _stub_db_for_auth(self._row(plaintext))
        resp = client.post(
            "/v1/agents",
            headers={"X-API-Key": plaintext},
            json=_agent_body(),
        )
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "glazkov"

    def test_valid_key_explicit_namespace_wins(self, client, _capture_create):
        plaintext = "valid-token"
        _stub_db_for_auth(self._row(plaintext))
        resp = client.post(
            "/v1/agents",
            headers={"X-API-Key": plaintext},
            json=_agent_body(namespace="finance-team"),
        )
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "finance-team"

    def test_alice_writes_to_her_namespace(self, client, _capture_create):
        """Different owner → different default namespace."""
        plaintext = "alice-token"
        _stub_db_for_auth(self._row(plaintext, owner="alice"))
        resp = client.post(
            "/v1/agents",
            headers={"X-API-Key": plaintext},
            json=_agent_body(),
        )
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "alice"


class TestAgentsCreateStrict:
    def test_no_key_401(self, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        _stub_db_for_auth(None)
        resp = client.post("/v1/agents", json=_agent_body())
        assert resp.status_code == 401
