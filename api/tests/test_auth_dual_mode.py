"""Tests for the dual-mode auth dependency (P1 §3 follow-up).

Iter #25 shipped strict-mode (`auth_required=True` enforced). This
iteration ships **opt-in mode** (`auth_required=False`, the default
for dev/CI):

* missing/empty header → anonymous AuthContext
* invalid/revoked/expired header → still 401 (no silent downgrade)
* valid header → full AuthContext (same as strict mode)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthContext, _anonymous_context, require_api_key
from app.db.models import ApiKey
from app.db.session import get_db
from app.services.api_key_service import _hash_key


def _build_row(
    *,
    key_hash: str = "h" * 64,
    owner: str = "glazkov",
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> ApiKey:
    import uuid
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


def _mock_db(row: ApiKey | None) -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


@pytest.fixture
def protected_app():
    app = FastAPI()

    @app.get("/who")
    async def _who(auth: AuthContext = Depends(require_api_key)) -> dict:
        return {
            "key_id": auth.key_id,
            "owner": auth.owner,
            "scopes": sorted(auth.scopes),
            "is_anonymous": auth.is_anonymous,
        }

    return app


@pytest.fixture
def client(protected_app):
    return TestClient(protected_app)


@pytest.fixture(autouse=True)
def _reset_overrides(protected_app):
    yield
    protected_app.dependency_overrides.clear()


def _bind(app, row):
    db = _mock_db(row)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override


# ---------------------------------------------------------------------------
# Opt-in mode (auth_required=False)
# ---------------------------------------------------------------------------


class TestOptInMode:
    """Default config: missing header yields anonymous context."""

    def test_missing_header_returns_anonymous(self, protected_app, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", False)
        _bind(protected_app, None)

        resp = client.get("/who")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_anonymous"] is True
        assert body["owner"] == "anonymous"
        assert body["scopes"] == []
        assert body["key_id"] == ""

    def test_empty_header_returns_anonymous(self, protected_app, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", False)
        _bind(protected_app, None)

        resp = client.get("/who", headers={"X-API-Key": ""})
        assert resp.status_code == 200
        assert resp.json()["is_anonymous"] is True

    def test_invalid_header_still_401_in_opt_in_mode(
        self, protected_app, client, monkeypatch
    ):
        """A revoked / unknown key NEVER silently downgrades — even in
        opt-in mode. Production deployments rely on this so leaked
        keys can't be wielded as anonymous credentials."""
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", False)
        _bind(protected_app, None)

        resp = client.get("/who", headers={"X-API-Key": "leaked-then-revoked"})
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_valid_header_returns_full_context(
        self, protected_app, client, monkeypatch
    ):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", False)
        plaintext = "valid-token"
        row = _build_row(
            key_hash=_hash_key(plaintext),
            owner="glazkov",
            scopes=["read:any"],
        )
        _bind(protected_app, row)

        resp = client.get("/who", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_anonymous"] is False
        assert body["owner"] == "glazkov"
        assert body["scopes"] == ["read:any"]


# ---------------------------------------------------------------------------
# Strict mode (auth_required=True)
# ---------------------------------------------------------------------------


class TestStrictMode:
    """Production config: missing header is 401, no anonymous fallback."""

    def test_missing_header_401(self, protected_app, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        _bind(protected_app, None)

        resp = client.get("/who")
        assert resp.status_code == 401
        # Detail mentions both auth schemes now that OIDC bearer is
        # also accepted (TODO §3 P3).
        assert resp.json()["detail"] == (
            "Missing X-API-Key or Authorization: Bearer header"
        )

    def test_valid_header_returns_full_context(
        self, protected_app, client, monkeypatch
    ):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        plaintext = "valid-token"
        row = _build_row(key_hash=_hash_key(plaintext), owner="alice")
        _bind(protected_app, row)

        resp = client.get("/who", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        assert resp.json()["owner"] == "alice"

    def test_revoked_key_401(self, protected_app, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        row = _build_row(revoked_at=datetime.now(timezone.utc))
        _bind(protected_app, row)

        resp = client.get("/who", headers={"X-API-Key": "any"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AuthContext.is_anonymous + custom anonymous owner
# ---------------------------------------------------------------------------


class TestAnonymousContext:
    def test_is_anonymous_property(self):
        anon = _anonymous_context()
        assert anon.is_anonymous is True
        assert anon.owner == "anonymous"
        assert anon.scopes == frozenset()
        assert anon.key_id == ""

    def test_named_context_not_anonymous(self):
        ctx = AuthContext(key_id="k", owner="alice", scopes=frozenset({"read"}))
        assert ctx.is_anonymous is False

    def test_anonymous_fails_scope_gate(self):
        """Anonymous contexts have no scopes — `require_scope` always 403s.

        This is the security guarantee: turning on a route's
        `Depends(require_api_key)` is non-breaking, but turning on a
        route's `auth.require_scope("evolve")` still gates the
        anonymous caller out."""
        from fastapi import HTTPException

        anon = _anonymous_context()
        with pytest.raises(HTTPException) as exc:
            anon.require_scope("evolve")
        assert exc.value.status_code == 403

    def test_custom_anonymous_owner(self, monkeypatch):
        """``settings.auth_anonymous_owner`` overrides the default
        ``"anonymous"`` label so deployments can tag unauthenticated
        traffic per environment (e.g. ``"dev"``, ``"ci"``)."""
        from app import auth as auth_mod

        monkeypatch.setattr(auth_mod.settings, "auth_anonymous_owner", "dev")
        anon = _anonymous_context()
        assert anon.owner == "dev"


# ---------------------------------------------------------------------------
# Iter #25 strict-mode tests must still pass
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """The strict-mode tests added in iter #25 still produce the same
    behaviour when settings explicitly enable strict mode."""

    def test_iter25_strict_unchanged(self, protected_app, client, monkeypatch):
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        _bind(protected_app, None)

        # All three failure modes from iter #25 still produce 401.
        for headers in [
            {},                          # missing
            {"X-API-Key": ""},           # empty
            {"X-API-Key": "made-up"},    # unknown
        ]:
            assert client.get("/who", headers=headers).status_code == 401
