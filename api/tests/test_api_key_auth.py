"""Tests for the API-key auth foundation (P1 §3).

Three layers: pure hash function, ``ApiKeyService`` against a mocked
async DB, and the ``require_api_key`` FastAPI dependency end-to-end
via TestClient.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthContext, require_api_key
from app.db.models import ApiKey
from app.db.session import get_db
from app.services.api_key_service import ApiKeyService, _hash_key, _generate_key


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHashKey:
    def test_returns_64_hex_chars(self):
        out = _hash_key("hello")
        assert len(out) == 64
        assert all(c in "0123456789abcdef" for c in out)

    def test_deterministic(self):
        assert _hash_key("hello") == _hash_key("hello")

    def test_different_inputs_different_hashes(self):
        assert _hash_key("a") != _hash_key("b")

    def test_handles_utf8(self):
        out = _hash_key("ёлка")  # cyrillic
        assert len(out) == 64


class TestGenerateKey:
    def test_returns_non_empty_string(self):
        k = _generate_key()
        assert isinstance(k, str)
        assert len(k) >= 40  # 32 bytes urlsafe ≈ 43 chars

    def test_unique_per_call(self):
        # 1024 keys, all distinct.
        keys = {_generate_key() for _ in range(1024)}
        assert len(keys) == 1024


# ---------------------------------------------------------------------------
# ApiKeyService — mocked DB
# ---------------------------------------------------------------------------


def _build_row(
    *,
    key_hash: str = "h" * 64,
    owner: str = "glazkov",
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> ApiKey:
    return ApiKey(
        key_id=uuid.uuid4(),
        key_hash=key_hash,
        owner=owner,
        label=None,
        scopes=list(scopes or []),
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def _mock_db(scalar_value: ApiKey | None = None) -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=scalar_value)
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[scalar_value] if scalar_value else [])
    result.scalars = MagicMock(return_value=scalars)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class TestCreateKey:
    @pytest.mark.asyncio
    async def test_returns_plaintext_only_once(self):
        db = _mock_db()
        svc = ApiKeyService(db)
        issued = await svc.create_key(owner="glazkov", scopes=["read:any"])

        # Plaintext returned to caller.
        assert isinstance(issued.plaintext, str) and len(issued.plaintext) >= 40
        # Hash stored on the row, plaintext nowhere on the DB call.
        db.add.assert_called_once()
        row = db.add.call_args.args[0]
        assert row.key_hash == _hash_key(issued.plaintext)
        # Sanity: persisted row does NOT carry the plaintext.
        assert not hasattr(row, "plaintext")

    @pytest.mark.asyncio
    async def test_scopes_default_to_empty(self):
        db = _mock_db()
        svc = ApiKeyService(db)
        issued = await svc.create_key(owner="alice")
        assert issued.scopes == []


class TestVerifyKey:
    @pytest.mark.asyncio
    async def test_known_key_returns_row(self):
        plaintext = "test-token-xyz"
        db = _mock_db(_build_row(key_hash=_hash_key(plaintext)))
        svc = ApiKeyService(db)
        row = await svc.verify_key(plaintext)
        assert row is not None

    @pytest.mark.asyncio
    async def test_unknown_key_returns_none(self):
        db = _mock_db(None)
        svc = ApiKeyService(db)
        assert await svc.verify_key("never-issued") is None

    @pytest.mark.asyncio
    async def test_empty_key_returns_none_without_db_hit(self):
        db = _mock_db(_build_row())
        svc = ApiKeyService(db)
        out = await svc.verify_key("")
        assert out is None
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_revoked_key_returns_none(self):
        row = _build_row(revoked_at=datetime.now(timezone.utc))
        db = _mock_db(row)
        svc = ApiKeyService(db)
        assert await svc.verify_key("any") is None

    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        row = _build_row(expires_at=past)
        db = _mock_db(row)
        svc = ApiKeyService(db)
        assert await svc.verify_key("any") is None

    @pytest.mark.asyncio
    async def test_future_expiry_passes(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        row = _build_row(expires_at=future)
        db = _mock_db(row)
        svc = ApiKeyService(db)
        assert await svc.verify_key("any") is row


class TestRevokeKey:
    @pytest.mark.asyncio
    async def test_revokes_active_row(self):
        row = _build_row()
        db = _mock_db(row)
        svc = ApiKeyService(db)
        ok = await svc.revoke_key(row.key_id)
        assert ok is True
        assert row.revoked_at is not None

    @pytest.mark.asyncio
    async def test_already_revoked_returns_false(self):
        row = _build_row(revoked_at=datetime.now(timezone.utc))
        db = _mock_db(row)
        svc = ApiKeyService(db)
        assert await svc.revoke_key(row.key_id) is False

    @pytest.mark.asyncio
    async def test_missing_returns_false(self):
        db = _mock_db(None)
        svc = ApiKeyService(db)
        assert await svc.revoke_key(uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# require_api_key — FastAPI dependency
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_protected_route() -> FastAPI:
    """A throwaway app with one protected handler that echoes the AuthContext."""
    app = FastAPI()

    @app.get("/protected")
    async def _protected(auth: AuthContext = Depends(require_api_key)) -> dict:
        return {
            "key_id": auth.key_id,
            "owner": auth.owner,
            "scopes": sorted(auth.scopes),
        }

    return app


@pytest.fixture
def client(app_with_protected_route):
    return TestClient(app_with_protected_route)


@pytest.fixture(autouse=True)
def _reset_overrides(app_with_protected_route):
    yield
    app_with_protected_route.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _strict_mode(monkeypatch):
    """Iter #25 tests predate dual-mode (iter #28). They assume
    strict-by-default behaviour — pin `auth_required=True` so the
    401-on-missing-header assertions remain valid."""
    from app import auth as auth_mod
    monkeypatch.setattr(auth_mod.settings, "auth_required", True)


def _bind_db(app: FastAPI, row: ApiKey | None) -> None:
    """Wire `get_db` to a session whose verify_key call returns `row`."""
    db = _mock_db(row)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override


class TestRequireApiKey:
    def test_missing_header_401(self, app_with_protected_route, client):
        _bind_db(app_with_protected_route, None)
        resp = client.get("/protected")
        assert resp.status_code == 401
        # Detail + WWW-Authenticate now list both schemes since OIDC
        # bearer auth is also accepted (TODO §3 P3).
        assert resp.json()["detail"] == (
            "Missing X-API-Key or Authorization: Bearer header"
        )
        assert resp.headers.get("WWW-Authenticate") == "Bearer, X-API-Key"

    def test_empty_header_401(self, app_with_protected_route, client):
        _bind_db(app_with_protected_route, None)
        resp = client.get("/protected", headers={"X-API-Key": ""})
        assert resp.status_code == 401

    def test_unknown_key_401(self, app_with_protected_route, client):
        _bind_db(app_with_protected_route, None)
        resp = client.get("/protected", headers={"X-API-Key": "made-up"})
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_revoked_key_401(self, app_with_protected_route, client):
        row = _build_row(revoked_at=datetime.now(timezone.utc))
        _bind_db(app_with_protected_route, row)
        resp = client.get("/protected", headers={"X-API-Key": "any"})
        assert resp.status_code == 401

    def test_expired_key_401(self, app_with_protected_route, client):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        row = _build_row(expires_at=past)
        _bind_db(app_with_protected_route, row)
        resp = client.get("/protected", headers={"X-API-Key": "any"})
        assert resp.status_code == 401

    def test_valid_key_returns_auth_context(self, app_with_protected_route, client):
        plaintext = "valid-token"
        row = _build_row(
            key_hash=_hash_key(plaintext),
            owner="glazkov",
            scopes=["read:any", "evolve"],
        )
        _bind_db(app_with_protected_route, row)
        resp = client.get("/protected", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        body = resp.json()
        assert body["owner"] == "glazkov"
        assert sorted(body["scopes"]) == ["evolve", "read:any"]


# ---------------------------------------------------------------------------
# AuthContext scope helpers
# ---------------------------------------------------------------------------


class TestAuthContextScopes:
    def test_has_scope(self):
        ctx = AuthContext(key_id="k", owner="o", scopes=frozenset({"read:any"}))
        assert ctx.has_scope("read:any") is True
        assert ctx.has_scope("evolve") is False

    def test_require_scope_passes(self):
        ctx = AuthContext(key_id="k", owner="o", scopes=frozenset({"evolve"}))
        ctx.require_scope("evolve")  # must not raise

    def test_require_scope_403_when_missing(self):
        from fastapi import HTTPException

        ctx = AuthContext(key_id="k", owner="o", scopes=frozenset())
        with pytest.raises(HTTPException) as exc_info:
            ctx.require_scope("write:agent_skill")
        assert exc_info.value.status_code == 403
        assert "write:agent_skill" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Migration 004
# ---------------------------------------------------------------------------


def _load_migration_004():
    import importlib.util
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app" / "db" / "migrations" / "versions" / "004_api_keys.py"
    )
    spec = importlib.util.spec_from_file_location("mig004", path)
    assert spec is not None and spec.loader is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


class TestMigration004:
    def test_revision_chain(self):
        mig = _load_migration_004()
        assert mig.revision == "004"
        assert mig.down_revision == "003"

    def test_upgrade_creates_api_keys_table(self):
        mig = _load_migration_004()
        captured: list = []

        def _spy_create_table(name, *cols, **kw):
            captured.append(("create_table", name, [c.name for c in cols]))

        def _spy_create_index(name, table, columns, **kw):
            captured.append(("create_index", name, table, list(columns)))

        with patch.object(mig.op, "create_table", side_effect=_spy_create_table), \
             patch.object(mig.op, "create_index", side_effect=_spy_create_index):
            mig.upgrade()

        # Exactly one create_table for `api_keys` with the documented columns.
        tables = [c for c in captured if c[0] == "create_table"]
        assert len(tables) == 1
        assert tables[0][1] == "api_keys"
        column_set = set(tables[0][2])
        assert column_set == {
            "key_id", "key_hash", "owner", "label",
            "scopes", "created_at", "expires_at", "revoked_at",
        }

        # Two indexes: unique key_hash + non-unique owner.
        idx = [c for c in captured if c[0] == "create_index"]
        idx_names = {c[1] for c in idx}
        assert "ix_api_keys_key_hash" in idx_names
        assert "ix_api_keys_owner" in idx_names

    def test_downgrade_drops_everything(self):
        mig = _load_migration_004()
        dropped: list = []

        def _spy_drop_table(name):
            dropped.append(("table", name))

        def _spy_drop_index(name, table_name=""):
            dropped.append(("index", name))

        with patch.object(mig.op, "drop_table", side_effect=_spy_drop_table), \
             patch.object(mig.op, "drop_index", side_effect=_spy_drop_index):
            mig.downgrade()

        assert ("table", "api_keys") in dropped
        assert ("index", "ix_api_keys_key_hash") in dropped
        assert ("index", "ix_api_keys_owner") in dropped
