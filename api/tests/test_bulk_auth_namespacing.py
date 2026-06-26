"""Tests for auth-driven namespace defaulting on the bulk endpoint
(P1 §3 follow-up — iteration #29)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthContext, _anonymous_context
from app.db.models import ApiKey
from app.db.session import get_db
from app.main import app
from app.models.requests import BulkSaveItem, EntityMeta
from app.routers.bulk import _apply_namespace_default
from app.services.api_key_service import _hash_key


# ---------------------------------------------------------------------------
# Pure helper: _apply_namespace_default
# ---------------------------------------------------------------------------


def _item(*, namespace: str | None = None) -> BulkSaveItem:
    return BulkSaveItem(
        entity_type="chain",
        meta=EntityMeta(name="x", namespace=namespace),
        content={"version": "1.1", "steps": [{"number": 1}]},
        channel="latest",
    )


class TestApplyNamespaceDefault:
    def test_anonymous_caller_no_default(self):
        """Opt-in mode anonymous → no namespace mutation."""
        item = _item(namespace=None)
        out = _apply_namespace_default(item, _anonymous_context())
        assert out.meta.namespace is None
        assert out is item  # short-circuit, no copy

    def test_authenticated_caller_no_namespace_gets_owner(self):
        item = _item(namespace=None)
        auth = AuthContext(
            key_id="k", owner="glazkov", scopes=frozenset()
        )
        out = _apply_namespace_default(item, auth)
        assert out.meta.namespace == "glazkov"
        # Original input unmutated.
        assert item.meta.namespace is None

    def test_authenticated_caller_explicit_namespace_wins(self):
        """Caller explicitly targeting a shared namespace stays
        verbatim — the service layer handles authorisation."""
        item = _item(namespace="shared-workspace")
        auth = AuthContext(
            key_id="k", owner="glazkov", scopes=frozenset()
        )
        out = _apply_namespace_default(item, auth)
        assert out.meta.namespace == "shared-workspace"
        assert out is item  # no mutation needed

    def test_no_mutation_of_input_item(self):
        """The helper must produce a new BulkSaveItem rather than
        mutate the request body in place."""
        item = _item(namespace=None)
        original_meta_id = id(item.meta)
        auth = AuthContext(
            key_id="k", owner="glazkov", scopes=frozenset()
        )
        out = _apply_namespace_default(item, auth)
        assert id(out.meta) != original_meta_id


# ---------------------------------------------------------------------------
# End-to-end via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def _entity_with_version():
    entity = MagicMock()
    entity.entity_id = uuid.uuid4()
    entity.entity_type = "chain"
    version = MagicMock()
    version.version_id = uuid.uuid4()
    return entity, version


@pytest.fixture
def _stub_save():
    """Capture the kwargs passed into the underlying service save so
    we can assert on `namespace`."""
    captured: list[dict] = []

    async def _spy(svc, item):
        captured.append({
            "entity_type": item.entity_type,
            "namespace": item.meta.namespace,
        })
        return (True, {
            "entity_type": item.entity_type,
            "entity_id": "x",
            "version_id": "v1",
            "channel": "latest",
        }, None)

    with patch("app.routers.bulk._save_one", new=_spy):
        yield captured


def _stub_db():
    async def _override():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override


def _stub_db_for_auth(row: ApiKey | None):
    """Wire `get_db` to a session whose `verify_key` returns `row`."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override


@pytest.fixture
def _ensure_opt_in(monkeypatch):
    """Pin opt-in mode so the bulk endpoint accepts no-key requests."""
    from app import auth as auth_mod
    monkeypatch.setattr(auth_mod.settings, "auth_required", False)


class TestBulkSaveAuthOptIn:
    """Default `auth_required=False`: no key → anonymous → no defaulting."""

    def test_no_key_keeps_namespace_unset(
        self, client, _stub_save, _ensure_opt_in
    ):
        _stub_db_for_auth(None)  # no key row even if asked
        resp = client.post("/v1/bulk/save", json={
            "items": [{
                "entity_type": "chain",
                "meta": {"name": "x"},
                "content": {"version": "1.1", "steps": [{"number": 1}]},
            }],
        })
        assert resp.status_code == 200
        assert _stub_save[0]["namespace"] is None

    def test_no_key_explicit_namespace_respected(
        self, client, _stub_save, _ensure_opt_in
    ):
        _stub_db_for_auth(None)
        resp = client.post("/v1/bulk/save", json={
            "items": [{
                "entity_type": "chain",
                "meta": {"name": "x", "namespace": "shared"},
                "content": {"version": "1.1", "steps": [{"number": 1}]},
            }],
        })
        assert resp.status_code == 200
        assert _stub_save[0]["namespace"] == "shared"


class TestBulkSaveAuthAuthenticated:
    """Valid X-API-Key → namespace defaults to auth.owner."""

    def test_valid_key_no_namespace_defaults_to_owner(
        self, client, _stub_save, _ensure_opt_in
    ):
        plaintext = "valid-token"
        row = ApiKey(
            key_id=uuid.uuid4(),
            key_hash=_hash_key(plaintext),
            owner="glazkov", label=None,
            scopes=[], created_at=datetime.now(timezone.utc),
            expires_at=None, revoked_at=None,
        )
        _stub_db_for_auth(row)
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
        assert _stub_save[0]["namespace"] == "glazkov"

    def test_valid_key_explicit_namespace_wins(
        self, client, _stub_save, _ensure_opt_in
    ):
        """Caller explicitly targeting another namespace is respected."""
        plaintext = "valid-token"
        row = ApiKey(
            key_id=uuid.uuid4(),
            key_hash=_hash_key(plaintext),
            owner="glazkov", label=None,
            scopes=[], created_at=datetime.now(timezone.utc),
            expires_at=None, revoked_at=None,
        )
        _stub_db_for_auth(row)
        resp = client.post(
            "/v1/bulk/save",
            headers={"X-API-Key": plaintext},
            json={"items": [{
                "entity_type": "chain",
                "meta": {"name": "x", "namespace": "shared-workspace"},
                "content": {"version": "1.1", "steps": [{"number": 1}]},
            }]},
        )
        assert resp.status_code == 200
        assert _stub_save[0]["namespace"] == "shared-workspace"

    def test_mixed_items_namespace_per_row(
        self, client, _stub_save, _ensure_opt_in
    ):
        """Item 0 has no namespace → defaults; item 1 explicit → kept."""
        plaintext = "valid-token"
        row = ApiKey(
            key_id=uuid.uuid4(),
            key_hash=_hash_key(plaintext),
            owner="glazkov", label=None,
            scopes=[], created_at=datetime.now(timezone.utc),
            expires_at=None, revoked_at=None,
        )
        _stub_db_for_auth(row)
        resp = client.post(
            "/v1/bulk/save",
            headers={"X-API-Key": plaintext},
            json={"items": [
                {"entity_type": "chain",
                 "meta": {"name": "auto"},  # no namespace
                 "content": {"version": "1.1", "steps": [{"number": 1}]}},
                {"entity_type": "agent",
                 "meta": {"name": "explicit", "namespace": "ops"},
                 "content": {"role": "x"}},
            ]},
        )
        assert resp.status_code == 200
        assert _stub_save[0]["namespace"] == "glazkov"
        assert _stub_save[1]["namespace"] == "ops"


class TestBulkSaveAuthStrict:
    """`auth_required=True` (production): no key → 401."""

    def test_no_key_401_in_strict_mode(self, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        _stub_db_for_auth(None)
        resp = client.post("/v1/bulk/save", json={
            "items": [{
                "entity_type": "chain",
                "meta": {"name": "x"},
                "content": {"version": "1.1", "steps": [{"number": 1}]},
            }],
        })
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing X-API-Key header"


class TestNoRegressionFromIter23:
    """Iter #23's bulk-save tests don't send X-API-Key → must still
    pass under the new dependency (opt-in mode defaults)."""

    def test_iter23_no_key_still_works(
        self, client, _stub_save, _ensure_opt_in
    ):
        _stub_db_for_auth(None)
        resp = client.post("/v1/bulk/save", json={
            "items": [
                {"entity_type": "chain",
                 "meta": {"name": "x"},
                 "content": {"version": "1.1", "steps": [{"number": 1}]}},
                {"entity_type": "agent",
                 "meta": {"name": "y"},
                 "content": {"role": "x"}},
            ],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success_count"] == 2
        assert body["error_count"] == 0
