"""Tests for the `make create-key` CLI module (P1 §3, iter #34).

Covers argument resolution (CLI flags vs. env vars), scope parsing,
expiry parsing, the printed output shape, and a full end-to-end run
with a mocked `ApiKeyService.create_key` (no DB I/O).
"""

from __future__ import annotations

import io
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.create_key import (
    _parse_expires_days,
    _parse_scopes,
    _print_issued,
    _resolve_args,
    main,
)
from app.services.api_key_service import IssuedKey


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestParseScopes:
    def test_none_returns_empty(self):
        assert _parse_scopes(None) == []

    def test_empty_returns_empty(self):
        assert _parse_scopes("") == []

    def test_single(self):
        assert _parse_scopes("read:any") == ["read:any"]

    def test_csv(self):
        assert _parse_scopes("read:any,evolve") == ["read:any", "evolve"]

    def test_strips_whitespace_and_blanks(self):
        assert _parse_scopes("read:any, ,  evolve ") == ["read:any", "evolve"]


class TestParseExpiresDays:
    def test_none_returns_none(self):
        assert _parse_expires_days(None) is None

    def test_empty_returns_none(self):
        assert _parse_expires_days("") is None

    def test_positive_returns_future(self):
        before = datetime.now(timezone.utc)
        result = _parse_expires_days("30")
        after = datetime.now(timezone.utc)
        assert before + timedelta(days=30) - timedelta(seconds=2) <= result
        assert result <= after + timedelta(days=30) + timedelta(seconds=2)

    def test_zero_rejected(self):
        with pytest.raises(ValueError, match="must be > 0"):
            _parse_expires_days("0")

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="must be > 0"):
            _parse_expires_days("-5")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            _parse_expires_days("forever")


# ---------------------------------------------------------------------------
# Argument resolution: CLI flags vs. environment
# ---------------------------------------------------------------------------


class TestResolveArgs:
    def test_owner_from_cli_flag(self, monkeypatch):
        monkeypatch.delenv("OWNER", raising=False)
        owner, scopes, label, expires_at = _resolve_args(["--owner", "alice"])
        assert owner == "alice"
        assert scopes == []
        assert label is None
        assert expires_at is None

    def test_owner_from_env(self, monkeypatch):
        monkeypatch.setenv("OWNER", "bob")
        owner, *_ = _resolve_args([])
        assert owner == "bob"

    def test_cli_flag_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OWNER", "bob")
        owner, *_ = _resolve_args(["--owner", "alice"])
        assert owner == "alice"

    def test_missing_owner_exits_2(self, monkeypatch):
        monkeypatch.delenv("OWNER", raising=False)
        with pytest.raises(SystemExit) as exc:
            _resolve_args([])
        assert exc.value.code == 2

    def test_scopes_csv_from_env(self, monkeypatch):
        monkeypatch.setenv("OWNER", "alice")
        monkeypatch.setenv("SCOPES", "read:any,evolve")
        _, scopes, *_ = _resolve_args([])
        assert scopes == ["read:any", "evolve"]

    def test_label_from_env(self, monkeypatch):
        monkeypatch.setenv("OWNER", "alice")
        monkeypatch.setenv("LABEL", "alice's laptop")
        _, _, label, _ = _resolve_args([])
        assert label == "alice's laptop"

    def test_expires_days_from_env(self, monkeypatch):
        monkeypatch.setenv("OWNER", "alice")
        monkeypatch.setenv("EXPIRES_DAYS", "7")
        _, _, _, expires_at = _resolve_args([])
        assert expires_at is not None
        delta = expires_at - datetime.now(timezone.utc)
        assert timedelta(days=6, hours=23) <= delta <= timedelta(days=7, hours=1)

    def test_bad_expires_days_exits_2(self, monkeypatch):
        monkeypatch.setenv("OWNER", "alice")
        monkeypatch.setenv("EXPIRES_DAYS", "-1")
        with pytest.raises(SystemExit) as exc:
            _resolve_args([])
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


class TestPrintIssued:
    def _key(self, **kw) -> IssuedKey:
        defaults = dict(
            plaintext="abc123xyz",
            key_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            owner="alice",
            scopes=["read:any"],
            label=None,
            created_at=datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc),
            expires_at=None,
        )
        defaults.update(kw)
        return IssuedKey(**defaults)

    def test_contains_plaintext_and_metadata(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_issued(self._key())
        out = buf.getvalue()
        assert "abc123xyz" in out
        assert "11111111-1111-1111-1111-111111111111" in out
        assert "alice" in out
        assert "read:any" in out
        # Warns operator that the plaintext is one-shot
        assert "not be shown again" in out
        assert "X-API-Key: abc123xyz" in out

    def test_no_scopes_renders_placeholder(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_issued(self._key(scopes=[]))
        assert "scopes:     (none)" in buf.getvalue()

    def test_no_expiry_renders_never(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_issued(self._key(expires_at=None))
        assert "expires_at: never" in buf.getvalue()

    def test_expiry_renders_iso(self):
        expiry = datetime(2026, 6, 16, tzinfo=timezone.utc)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_issued(self._key(expires_at=expiry))
        assert "2026-06-16T00:00:00+00:00" in buf.getvalue()


# ---------------------------------------------------------------------------
# End-to-end main(): mocked DB
# ---------------------------------------------------------------------------


class TestMainE2E:
    def test_success_path_returns_0_and_prints_plaintext(self, monkeypatch):
        issued = IssuedKey(
            plaintext="end-to-end-token",
            key_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            owner="alice",
            scopes=["read:any"],
            label="cli-test",
            created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
            expires_at=None,
        )

        async def _fake_create_key(self, **kw):
            # Capture for assertion
            _fake_create_key.captured = kw  # type: ignore[attr-defined]
            return issued

        # No env vars set so we rely on CLI flags entirely.
        monkeypatch.delenv("OWNER", raising=False)
        monkeypatch.delenv("SCOPES", raising=False)
        monkeypatch.delenv("LABEL", raising=False)
        monkeypatch.delenv("EXPIRES_DAYS", raising=False)

        # Patch the service method + bypass the real DB session.
        from app.services.api_key_service import ApiKeyService

        fake_db = MagicMock()
        fake_session_cm = MagicMock()
        fake_session_cm.__aenter__ = AsyncMock(return_value=fake_db)
        fake_session_cm.__aexit__ = AsyncMock(return_value=None)

        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with (
            patch.object(ApiKeyService, "create_key", new=_fake_create_key),
            patch("app.create_key.async_session", new=MagicMock(return_value=fake_session_cm)),
            redirect_stdout(buf_out),
            redirect_stderr(buf_err),
        ):
            rc = main(["--owner", "alice", "--scopes", "read:any", "--label", "cli-test"])

        assert rc == 0
        assert "end-to-end-token" in buf_out.getvalue()
        # Confirm the service got the parsed args.
        captured = _fake_create_key.captured  # type: ignore[attr-defined]
        assert captured["owner"] == "alice"
        assert captured["scopes"] == ["read:any"]
        assert captured["label"] == "cli-test"
        assert captured["expires_at"] is None

    def test_missing_owner_exits_2_no_db_call(self, monkeypatch):
        monkeypatch.delenv("OWNER", raising=False)
        buf_err = io.StringIO()
        with redirect_stderr(buf_err), pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2
        assert "OWNER" in buf_err.getvalue()

    def test_db_failure_returns_1(self, monkeypatch):
        """An unhandled exception (e.g. DB not migrated) → exit code 1."""
        monkeypatch.delenv("OWNER", raising=False)

        async def _boom(self, **kw):
            raise RuntimeError("connection refused")

        fake_db = MagicMock()
        fake_session_cm = MagicMock()
        fake_session_cm.__aenter__ = AsyncMock(return_value=fake_db)
        fake_session_cm.__aexit__ = AsyncMock(return_value=None)

        from app.services.api_key_service import ApiKeyService

        buf_err = io.StringIO()
        with (
            patch.object(ApiKeyService, "create_key", new=_boom),
            patch("app.create_key.async_session", new=MagicMock(return_value=fake_session_cm)),
            redirect_stderr(buf_err),
        ):
            rc = main(["--owner", "alice"])

        assert rc == 1
        assert "failed to issue key" in buf_err.getvalue()
        assert "connection refused" in buf_err.getvalue()
