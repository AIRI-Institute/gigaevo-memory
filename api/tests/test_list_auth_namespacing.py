"""Tests for auth-driven default namespace filtering on list endpoints
(P1 §3 follow-up — iteration #41, closes the read-side rollout).

Two layers:

  1. Pure helper ``default_read_namespace_for(query_namespace, auth)``:
     anonymous pass-through, authenticated-explicit-wins,
     authenticated-with-read:any-stays-None,
     authenticated-without-read:any-defaults-to-owner.

  2. End-to-end on ``GET /v1/agents`` (representative typed list
     endpoint; the other 4 routers share the same wiring): the
     ``namespace=`` kwarg forwarded to ``EntityService.list_entities``
     matches the helper's verdict.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    SCOPE_READ_ANY,
    AuthContext,
    _anonymous_context,
    default_read_namespace_for,
    require_api_key,
)
from app.db.models import ApiKey
from app.db.session import get_db
from app.main import app
from app.services.api_key_service import _hash_key


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------


class TestDefaultReadNamespaceForHelper:
    def test_anonymous_passthrough_none(self):
        assert default_read_namespace_for(None, _anonymous_context()) is None

    def test_anonymous_passthrough_explicit(self):
        """Anonymous caller in dev/CI keeps full visibility."""
        assert (
            default_read_namespace_for("shared", _anonymous_context()) == "shared"
        )

    def test_authenticated_explicit_query_respected(self):
        auth = AuthContext(key_id="k", owner="glazkov", scopes=frozenset())
        assert (
            default_read_namespace_for("finance-team", auth) == "finance-team"
        )

    def test_authenticated_no_query_no_scope_defaults_to_owner(self):
        auth = AuthContext(key_id="k", owner="glazkov", scopes=frozenset())
        assert default_read_namespace_for(None, auth) == "glazkov"

    def test_authenticated_no_query_with_read_any_returns_none(self):
        """``read:any`` opts the caller into cross-namespace reads."""
        auth = AuthContext(
            key_id="k", owner="glazkov", scopes=frozenset({SCOPE_READ_ANY})
        )
        assert default_read_namespace_for(None, auth) is None

    def test_authenticated_explicit_query_wins_over_read_any(self):
        """Even with ``read:any``, an explicit ``?namespace=X`` is
        respected — caller is deliberately narrowing the query."""
        auth = AuthContext(
            key_id="k", owner="glazkov", scopes=frozenset({SCOPE_READ_ANY})
        )
        assert (
            default_read_namespace_for("other-team", auth) == "other-team"
        )

    def test_pure_function_no_side_effects(self):
        """No DB I/O, no mutation — safe to call before any DB call."""
        auth = AuthContext(key_id="k", owner="alice", scopes=frozenset())
        for _ in range(100):
            assert default_read_namespace_for(None, auth) == "alice"
            assert default_read_namespace_for("x", auth) == "x"


# ---------------------------------------------------------------------------
# End-to-end on the agents list endpoint
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


@pytest.fixture
def _capture_list():
    """Capture the kwargs passed into ``EntityService.list_entities``
    so tests can assert on the ``namespace`` value forwarded."""
    captured: dict = {}

    async def _spy(self, **kw):
        captured.update(kw)
        return ([], None, False)

    from app.services.entity_service import EntityService

    with patch.object(EntityService, "list_entities", new=_spy):
        yield captured


def _row(plaintext: str, owner: str = "glazkov", scopes: list[str] | None = None) -> ApiKey:
    return ApiKey(
        key_id=uuid.uuid4(),
        key_hash=_hash_key(plaintext),
        owner=owner,
        label=None,
        scopes=list(scopes or []),
        created_at=datetime.now(timezone.utc),
        expires_at=None,
        revoked_at=None,
    )


class TestAgentsListAnonymous:
    def test_no_key_no_namespace_passes_none(self, client, _capture_list):
        _stub_db_for_auth(None)
        resp = client.get("/v1/agents")
        assert resp.status_code == 200
        assert _capture_list["namespace"] is None

    def test_no_key_explicit_namespace_respected(self, client, _capture_list):
        _stub_db_for_auth(None)
        resp = client.get("/v1/agents?namespace=shared")
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "shared"


class TestAgentsListAuthenticated:
    def test_valid_key_no_namespace_defaults_to_owner(self, client, _capture_list):
        plaintext = "valid-token"
        _stub_db_for_auth(_row(plaintext))
        resp = client.get("/v1/agents", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "glazkov"

    def test_valid_key_explicit_namespace_wins(self, client, _capture_list):
        plaintext = "valid-token"
        _stub_db_for_auth(_row(plaintext))
        resp = client.get(
            "/v1/agents?namespace=finance-team",
            headers={"X-API-Key": plaintext},
        )
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "finance-team"

    def test_alice_lists_her_namespace_by_default(self, client, _capture_list):
        plaintext = "alice-token"
        _stub_db_for_auth(_row(plaintext, owner="alice"))
        resp = client.get("/v1/agents", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "alice"


class TestAgentsListReadAnyScope:
    def test_read_any_no_namespace_returns_all(self, client, _capture_list):
        """A key with ``read:any`` and no ``?namespace`` query sees
        every namespace (``EntityService.list_entities`` gets
        ``namespace=None``)."""
        plaintext = "ops-token"
        _stub_db_for_auth(_row(plaintext, scopes=["read:any"]))
        resp = client.get("/v1/agents", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        assert _capture_list["namespace"] is None

    def test_read_any_explicit_query_still_wins(self, client, _capture_list):
        """Even with ``read:any``, an explicit ``?namespace`` narrows
        the query — caller knows what they want."""
        plaintext = "ops-token"
        _stub_db_for_auth(_row(plaintext, scopes=["read:any"]))
        resp = client.get(
            "/v1/agents?namespace=finance-team",
            headers={"X-API-Key": plaintext},
        )
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "finance-team"


class TestStrictModeListAuth:
    def test_no_key_returns_401(self, client, monkeypatch):
        """Strict mode requires a key even on list endpoints."""
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        _stub_db_for_auth(None)
        resp = client.get("/v1/agents")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Direct dependency override exercises the same path for memory_cards/steps,
# which previously had no ``?namespace`` query param at all.
# ---------------------------------------------------------------------------


class TestMemoryCardsListNamespaceAdded:
    """memory_cards' list endpoint gained a ``?namespace`` query
    parameter as part of iter #41; confirm the auth-driven default
    works there too."""

    def test_authenticated_default_namespace(self, client, _capture_list):
        plaintext = "valid-token"
        _stub_db_for_auth(_row(plaintext))
        resp = client.get(
            "/v1/memory-cards", headers={"X-API-Key": plaintext}
        )
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "glazkov"

    def test_anonymous_keeps_none(self, client, _capture_list):
        _stub_db_for_auth(None)
        resp = client.get("/v1/memory-cards")
        assert resp.status_code == 200
        assert _capture_list["namespace"] is None


class TestStepsListNamespaceAdded:
    """Same as memory_cards: steps' list gained ``?namespace`` and
    auth-driven defaulting in this iteration."""

    def test_authenticated_default_namespace(self, client, _capture_list):
        plaintext = "valid-token"
        _stub_db_for_auth(_row(plaintext))
        resp = client.get("/v1/steps", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "glazkov"


# ---------------------------------------------------------------------------
# Direct override path — confirms the helper end-to-end via
# `app.dependency_overrides[require_api_key]` (cleaner than DB stubbing).
# ---------------------------------------------------------------------------


class TestDependencyOverridePath:
    def test_inject_read_any_context_via_override(self, client, _capture_list):
        def _override():
            return AuthContext(
                key_id="ops",
                owner="ops-team",
                scopes=frozenset({SCOPE_READ_ANY}),
            )
        app.dependency_overrides[require_api_key] = _override
        resp = client.get("/v1/agents")
        assert resp.status_code == 200
        assert _capture_list["namespace"] is None

    def test_inject_scopeless_context_defaults_to_owner(self, client, _capture_list):
        def _override():
            return AuthContext(
                key_id="user",
                owner="dave",
                scopes=frozenset(),
            )
        app.dependency_overrides[require_api_key] = _override
        resp = client.get("/v1/agents")
        assert resp.status_code == 200
        assert _capture_list["namespace"] == "dave"
