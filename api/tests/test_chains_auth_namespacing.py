"""Tests for auth + namespace defaulting on the chains router
(P1 §3 follow-up — iteration #30) + shared `default_namespace_for`
helper."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthContext, _anonymous_context, default_namespace_for
from app.db.models import ApiKey
from app.db.session import get_db
from app.main import app
from app.services.api_key_service import _hash_key


# ---------------------------------------------------------------------------
# Pure helper: default_namespace_for
# ---------------------------------------------------------------------------


class TestDefaultNamespaceForHelper:
    def test_anonymous_passthrough_none(self):
        assert default_namespace_for(None, _anonymous_context()) is None

    def test_anonymous_passthrough_explicit(self):
        """Anonymous caller can still target a shared workspace."""
        assert default_namespace_for("shared", _anonymous_context()) == "shared"

    def test_authenticated_no_namespace_uses_owner(self):
        auth = AuthContext(key_id="k", owner="glazkov", scopes=frozenset())
        assert default_namespace_for(None, auth) == "glazkov"

    def test_authenticated_explicit_wins(self):
        auth = AuthContext(key_id="k", owner="glazkov", scopes=frozenset())
        assert default_namespace_for("finance-team", auth) == "finance-team"

    def test_pure_function_no_side_effects(self):
        """No DB I/O, no mutation — call millions of times if you want."""
        auth = AuthContext(key_id="k", owner="alice", scopes=frozenset())
        for _ in range(100):
            assert default_namespace_for(None, auth) == "alice"
            assert default_namespace_for("x", auth) == "x"


# ---------------------------------------------------------------------------
# End-to-end via TestClient on POST /v1/chains
# ---------------------------------------------------------------------------


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


def _chain_body(*, namespace: str | None = None) -> dict:
    body: dict = {
        "meta": {"name": "x"},
        "content": {
            "version": "1.1",
            "max_workers": 1,
            "metadata": {},
            "search_config": {},
            "steps": [{"number": 1}],
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
        # Build canned entity + version.
        entity = MagicMock()
        entity.entity_id = uuid.uuid4()
        entity.entity_type = "chain"
        entity.favourite = False
        entity.run_count = 0
        entity.last_run_at = None
        entity.display_name = "x"
        entity.description = None
        version = MagicMock()
        version.version_id = uuid.uuid4()
        version.content_json = kw["content"]
        version.meta_json = {}
        return entity, version

    from app.services.entity_service import EntityService

    with patch.object(EntityService, "create_entity", new=_spy):
        yield captured


class TestChainsCreateOptIn:
    def test_no_key_namespace_stays_none(self, client, _capture_create):
        _stub_db_for_auth(None)
        resp = client.post("/v1/chains", json=_chain_body())
        assert resp.status_code == 201
        assert _capture_create["namespace"] is None

    def test_no_key_explicit_namespace_respected(self, client, _capture_create):
        _stub_db_for_auth(None)
        resp = client.post("/v1/chains", json=_chain_body(namespace="shared"))
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "shared"


class TestChainsCreateAuthenticated:
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
            "/v1/chains",
            headers={"X-API-Key": plaintext},
            json=_chain_body(),
        )
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "glazkov"

    def test_valid_key_explicit_namespace_wins(self, client, _capture_create):
        plaintext = "valid-token"
        _stub_db_for_auth(self._row(plaintext))
        resp = client.post(
            "/v1/chains",
            headers={"X-API-Key": plaintext},
            json=_chain_body(namespace="finance-team"),
        )
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "finance-team"

    def test_alice_writes_to_her_namespace(self, client, _capture_create):
        """Different owner → different default namespace."""
        plaintext = "alice-token"
        _stub_db_for_auth(self._row(plaintext, owner="alice"))
        resp = client.post(
            "/v1/chains",
            headers={"X-API-Key": plaintext},
            json=_chain_body(),
        )
        assert resp.status_code == 201
        assert _capture_create["namespace"] == "alice"


class TestChainsCreateStrict:
    def test_no_key_401(self, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        _stub_db_for_auth(None)
        resp = client.post("/v1/chains", json=_chain_body())
        assert resp.status_code == 401


class TestBulkRefactorNoRegression:
    """Iter #29's bulk tests must still pass after the bulk router was
    refactored to use the shared `default_namespace_for` helper."""

    def test_bulk_anonymous_still_keeps_none(self, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", False)
        _stub_db_for_auth(None)
        captured: dict = {}

        async def _spy(svc, item):
            captured["namespace"] = item.meta.namespace
            return (True, {"entity_type": "chain", "entity_id": "x",
                           "version_id": "v1", "channel": "latest"}, None)

        with patch("app.routers.bulk._save_one", new=_spy):
            resp = client.post("/v1/bulk/save", json={"items": [{
                "entity_type": "chain",
                "meta": {"name": "x"},
                "content": {"version": "1.1", "steps": [{"number": 1}]},
            }]})
        assert resp.status_code == 200
        assert captured["namespace"] is None

    def test_bulk_authenticated_still_defaults(self, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", False)
        plaintext = "valid-token"
        row = ApiKey(
            key_id=uuid.uuid4(), key_hash=_hash_key(plaintext),
            owner="glazkov", label=None, scopes=[],
            created_at=datetime.now(timezone.utc),
            expires_at=None, revoked_at=None,
        )
        _stub_db_for_auth(row)
        captured: dict = {}

        async def _spy(svc, item):
            captured["namespace"] = item.meta.namespace
            return (True, {"entity_type": "chain", "entity_id": "x",
                           "version_id": "v1", "channel": "latest"}, None)

        with patch("app.routers.bulk._save_one", new=_spy):
            resp = client.post(
                "/v1/bulk/save",
                headers={"X-API-Key": plaintext},
                json={"items": [{
                    "entity_type": "chain",
                    "meta": {"name": "x"},
                    "content": {"version": "1.1", "steps": [{"number": 1}]},
                }]},
            )
        assert resp.status_code == 200
        assert captured["namespace"] == "glazkov"
