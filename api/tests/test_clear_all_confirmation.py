"""Tests for the two guards on ``POST /v1/maintenance/clear-all``:
the ``clear:all`` scope check (iter #37) and the X-Confirm header
guard (iter #19).

The endpoint is destructive (soft-deletes every entity, optionally
filtered by type). The server requires:

  1. The caller hold the ``clear:all`` scope — anonymous opt-in
     callers always 403 here, since they carry an empty scope set.
  2. ``X-Confirm: yes-i-really-mean-it`` on every call — a
     deliberately-long phrase that's un-mistakable in shell history
     and prevents accidental `curl -X POST` from a fat-finger.

The scope check runs first; tests below stub the auth dependency
with a context carrying ``clear:all`` so the X-Confirm assertions can
still be exercised.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SCOPE_CLEAR_ALL, AuthContext, require_api_key
from app.main import app
from app.routers.entities import CLEAR_ALL_CONFIRM_TOKEN


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def _admin_auth():
    """Inject an authenticated context carrying ``clear:all``."""
    def _override() -> AuthContext:
        return AuthContext(
            key_id="admin-key",
            owner="admin",
            scopes=frozenset({SCOPE_CLEAR_ALL}),
        )
    app.dependency_overrides[require_api_key] = _override
    yield


@pytest.fixture(autouse=True)
def _stub_db_and_redis():
    """Make the endpoint reachable without a real DB / Redis:

    * `get_db` yields a dummy session — won't be touched until we
      pass the X-Confirm gate.
    * `EntityService.clear_all` is patched to return a canned dict so
      successful calls don't hit Postgres.
    """
    from app.db import session as _session
    from app.services.entity_service import EntityService

    async def _dummy_db():
        yield AsyncMock()

    with patch.object(_session, "get_db", _dummy_db), patch.object(
        EntityService, "clear_all", new=AsyncMock(return_value={"chain": 0})
    ):
        yield


class TestConfirmHeaderEnforcement:
    """X-Confirm guard — exercised after the scope gate is satisfied
    by the ``_admin_auth`` fixture override."""

    def test_no_header_returns_412(self, client, _admin_auth):
        """Without the header the endpoint must NOT touch the database."""
        resp = client.post("/v1/maintenance/clear-all")
        assert resp.status_code == 412
        body = resp.json()
        assert "X-Confirm" in body["detail"]
        assert CLEAR_ALL_CONFIRM_TOKEN in body["detail"]

    def test_wrong_value_returns_412(self, client, _admin_auth):
        resp = client.post(
            "/v1/maintenance/clear-all",
            headers={"X-Confirm": "yes"},  # close but not quite
        )
        assert resp.status_code == 412

    def test_empty_value_returns_412(self, client, _admin_auth):
        resp = client.post(
            "/v1/maintenance/clear-all",
            headers={"X-Confirm": ""},
        )
        assert resp.status_code == 412

    def test_correct_value_passes_gate(self, client, _admin_auth):
        """The canonical phrase admits the call."""
        resp = client.post(
            "/v1/maintenance/clear-all",
            headers={"X-Confirm": CLEAR_ALL_CONFIRM_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json() == {"deleted": {"chain": 0}}

    def test_case_sensitivity(self, client, _admin_auth):
        """Server check is exact-match; uppercase variants reject."""
        resp = client.post(
            "/v1/maintenance/clear-all",
            headers={"X-Confirm": CLEAR_ALL_CONFIRM_TOKEN.upper()},
        )
        assert resp.status_code == 412

    def test_entity_type_filter_combined_with_confirm(self, client, _admin_auth):
        resp = client.post(
            "/v1/maintenance/clear-all?entity_type=chain",
            headers={"X-Confirm": CLEAR_ALL_CONFIRM_TOKEN},
        )
        assert resp.status_code == 200

    def test_entity_type_validated_after_confirm(self, client, _admin_auth):
        """Confirm header passes → entity_type validation runs → 400."""
        resp = client.post(
            "/v1/maintenance/clear-all?entity_type=BOGUS",
            headers={"X-Confirm": CLEAR_ALL_CONFIRM_TOKEN},
        )
        assert resp.status_code == 400
        assert "Invalid entity type" in resp.json()["detail"]

    def test_invalid_entity_type_without_confirm_still_412(self, client, _admin_auth):
        """The X-Confirm guard fires BEFORE entity_type validation —
        a bad entity_type doesn't leak the existence of the endpoint."""
        resp = client.post(
            "/v1/maintenance/clear-all?entity_type=BOGUS",
            # no X-Confirm
        )
        assert resp.status_code == 412


class TestScopeGate:
    """``clear:all`` scope gate — fires before X-Confirm so unauthorised
    callers don't even learn whether the X-Confirm phrase is right."""

    def test_anonymous_opt_in_returns_403(self, client, monkeypatch):
        """In opt-in mode the anonymous fallback carries empty scopes,
        so the scope check rejects it even with the X-Confirm token."""
        from app import auth as auth_mod
        monkeypatch.setattr(auth_mod.settings, "auth_required", False)
        resp = client.post(
            "/v1/maintenance/clear-all",
            headers={"X-Confirm": CLEAR_ALL_CONFIRM_TOKEN},
        )
        assert resp.status_code == 403
        assert "clear:all" in resp.json()["detail"]

    def test_authenticated_without_clear_all_scope_returns_403(self, client):
        """A regular `glazkov` key without `clear:all` cannot wipe."""
        def _override() -> AuthContext:
            return AuthContext(
                key_id="user-key",
                owner="glazkov",
                scopes=frozenset({"read:any"}),  # no clear:all
            )
        app.dependency_overrides[require_api_key] = _override

        resp = client.post(
            "/v1/maintenance/clear-all",
            headers={"X-Confirm": CLEAR_ALL_CONFIRM_TOKEN},
        )
        assert resp.status_code == 403
        assert "clear:all" in resp.json()["detail"]

    def test_scope_gate_fires_before_x_confirm(self, client):
        """Even with X-Confirm omitted, a scopeless caller gets 403,
        not 412 — the scope gate runs first."""
        def _override() -> AuthContext:
            return AuthContext(
                key_id="user-key",
                owner="glazkov",
                scopes=frozenset(),
            )
        app.dependency_overrides[require_api_key] = _override

        resp = client.post("/v1/maintenance/clear-all")  # no X-Confirm
        assert resp.status_code == 403


class TestConfirmTokenConstantStable:
    """The sentinel is part of the API contract — a typo or rename
    would silently break every client that hard-codes it."""

    def test_token_is_expected_phrase(self):
        assert CLEAR_ALL_CONFIRM_TOKEN == "yes-i-really-mean-it"
