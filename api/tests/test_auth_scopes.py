"""Tests for the canonical scope vocabulary + Role presets (P2 §3,
iter #37).

Covers:
  * Scope string constants have the expected values (so client code
    can hard-code them safely).
  * ``ALL_SCOPES`` enumerates every known scope.
  * Role presets bundle the expected scopes.
  * ``AuthContext.require_scope`` accepts both canonical-string and
    free-form scopes (forward compat for deployment-specific tags).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import (
    ALL_SCOPES,
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_READER,
    SCOPE_ADMIN_KEYS,
    SCOPE_CLEAR_ALL,
    SCOPE_DELETE_ANY,
    SCOPE_EVOLVE,
    SCOPE_READ_ANY,
    SCOPE_WRITE_ANY,
    AuthContext,
)


# ---------------------------------------------------------------------------
# Scope vocabulary
# ---------------------------------------------------------------------------


class TestScopeStrings:
    def test_canonical_values(self):
        """The string values are part of the wire contract — a typo
        or rename would silently break every key the operator issued."""
        assert SCOPE_READ_ANY == "read:any"
        assert SCOPE_WRITE_ANY == "write:any"
        assert SCOPE_DELETE_ANY == "delete:any"
        assert SCOPE_CLEAR_ALL == "clear:all"
        assert SCOPE_ADMIN_KEYS == "admin:keys"
        assert SCOPE_EVOLVE == "evolve"

    def test_all_scopes_enumerates_every_constant(self):
        """``ALL_SCOPES`` is the inventory: drift between it and the
        individual constants is a documentation bug."""
        assert ALL_SCOPES == frozenset({
            "read:any",
            "write:any",
            "delete:any",
            "clear:all",
            "admin:keys",
            "evolve",
        })

    def test_all_scopes_is_immutable(self):
        """frozenset prevents accidental mutation elsewhere."""
        assert isinstance(ALL_SCOPES, frozenset)


# ---------------------------------------------------------------------------
# Role presets
# ---------------------------------------------------------------------------


class TestRolePresets:
    def test_reader_role(self):
        assert ROLE_READER == frozenset({SCOPE_READ_ANY})

    def test_editor_role(self):
        assert ROLE_EDITOR == frozenset({SCOPE_READ_ANY, SCOPE_WRITE_ANY})

    def test_admin_role_carries_every_scope(self):
        """The admin role is the explicit ``ALL_SCOPES`` set — so adding
        a new scope automatically extends admin without missed wiring."""
        assert ROLE_ADMIN == ALL_SCOPES

    def test_roles_are_immutable(self):
        for role in (ROLE_READER, ROLE_EDITOR, ROLE_ADMIN):
            assert isinstance(role, frozenset)

    def test_editor_strictly_more_than_reader(self):
        assert ROLE_READER < ROLE_EDITOR

    def test_admin_strictly_more_than_editor(self):
        assert ROLE_EDITOR < ROLE_ADMIN


# ---------------------------------------------------------------------------
# AuthContext + scope gate behaviour
# ---------------------------------------------------------------------------


class TestAuthContextWithScopes:
    def _ctx(self, *scopes: str) -> AuthContext:
        return AuthContext(
            key_id="k",
            owner="alice",
            scopes=frozenset(scopes),
        )

    def test_reader_can_read_any(self):
        ctx = AuthContext(key_id="k", owner="alice", scopes=ROLE_READER)
        assert ctx.has_scope(SCOPE_READ_ANY)
        ctx.require_scope(SCOPE_READ_ANY)  # no raise

    def test_reader_cannot_clear_all(self):
        ctx = AuthContext(key_id="k", owner="alice", scopes=ROLE_READER)
        assert not ctx.has_scope(SCOPE_CLEAR_ALL)
        with pytest.raises(HTTPException) as exc:
            ctx.require_scope(SCOPE_CLEAR_ALL)
        assert exc.value.status_code == 403
        assert "clear:all" in exc.value.detail

    def test_editor_can_read_and_write_but_not_clear(self):
        ctx = AuthContext(key_id="k", owner="alice", scopes=ROLE_EDITOR)
        ctx.require_scope(SCOPE_READ_ANY)
        ctx.require_scope(SCOPE_WRITE_ANY)
        with pytest.raises(HTTPException):
            ctx.require_scope(SCOPE_CLEAR_ALL)

    def test_admin_passes_every_canonical_gate(self):
        ctx = AuthContext(key_id="k", owner="alice", scopes=ROLE_ADMIN)
        for scope in ALL_SCOPES:
            ctx.require_scope(scope)  # no raise

    def test_free_form_scopes_still_work(self):
        """Deployments can issue keys with deployment-specific scope
        strings (e.g. ``"finance-team"``); ``has_scope`` doesn't
        validate against ``ALL_SCOPES`` so the mechanism is open."""
        ctx = self._ctx("finance-team")
        assert ctx.has_scope("finance-team")
        ctx.require_scope("finance-team")  # no raise
