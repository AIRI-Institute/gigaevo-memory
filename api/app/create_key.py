"""CLI entry point for issuing API keys (P1 §3).

Wired into the project ``Makefile`` as::

    make create-key OWNER=alice
    make create-key OWNER=alice SCOPES=read:any,evolve LABEL="alice's laptop"
    make create-key OWNER=alice EXPIRES_DAYS=30

The plaintext token is printed exactly once. After this command returns,
the plaintext can never be recovered from the database — the operator
should copy it into a secrets manager / pass it to the principal over
a secure channel immediately.

Exits with status 0 on success, 2 on usage errors, 1 on any other
failure (DB connection refused, migration not applied, etc.). Designed
to be safe to run against an empty DB after ``make migrate``.

Usage flags can also be supplied as `--`-prefixed CLI args, which makes
the script convenient to call without going through the Makefile::

    uv run python -m app.create_key --owner alice --scopes read:any
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from .db.session import async_session
from .services.api_key_service import ApiKeyService, IssuedKey


def _parse_scopes(raw: str | None) -> list[str]:
    """Parse a comma-separated scope list. ``None`` / empty → ``[]``.

    Tokens are stripped of surrounding whitespace and empty tokens are
    dropped, so ``"read:any, ,evolve "`` → ``["read:any", "evolve"]``.
    """
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _parse_expires_days(raw: str | None) -> datetime | None:
    """Convert an ``EXPIRES_DAYS=N`` value into a UTC ``datetime``.

    Returns ``None`` for missing / empty input (key never expires).
    Raises ``ValueError`` on non-numeric or non-positive values so the
    operator notices typos before issuing a forever-key by accident.
    """
    if not raw:
        return None
    days = int(raw)
    if days <= 0:
        raise ValueError(f"EXPIRES_DAYS must be > 0, got {days}")
    return datetime.now(timezone.utc) + timedelta(days=days)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser. Flag values override env vars."""
    p = argparse.ArgumentParser(
        prog="create_key",
        description="Issue a new API key. Plaintext printed exactly once.",
    )
    p.add_argument("--owner", help="Principal owning the key (e.g. alice).")
    p.add_argument(
        "--scopes",
        help="Comma-separated scopes (e.g. 'read:any,evolve'). Default: none.",
    )
    p.add_argument("--label", help="Human-readable label (e.g. 'alice's laptop').")
    p.add_argument(
        "--expires-days",
        help="Expire the key after N days. Default: never expires.",
    )
    return p


def _resolve_args(argv: list[str] | None) -> tuple[str, list[str], str | None, datetime | None]:
    """Merge CLI flags with environment variables. Flags take precedence.

    Returns the resolved ``(owner, scopes, label, expires_at)`` tuple
    or exits the process with status 2 on usage errors (no owner,
    bad expires-days).
    """
    args = _build_parser().parse_args(argv)
    owner = args.owner or os.environ.get("OWNER")
    if not owner:
        print(
            "error: missing required OWNER (pass --owner or set OWNER=...)",
            file=sys.stderr,
        )
        sys.exit(2)
    scopes = _parse_scopes(args.scopes or os.environ.get("SCOPES"))
    label = args.label or os.environ.get("LABEL") or None
    expires_raw = args.expires_days or os.environ.get("EXPIRES_DAYS")
    try:
        expires_at = _parse_expires_days(expires_raw)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    return owner, scopes, label, expires_at


def _print_issued(key: IssuedKey) -> None:
    """Print the issued key. The plaintext is the only secret line."""
    expires_repr = key.expires_at.isoformat() if key.expires_at else "never"
    label_repr = key.label or "(none)"
    print("API key issued. Save the plaintext now — it will not be shown again.")
    print()
    print(f"  plaintext:  {key.plaintext}")
    print(f"  key_id:     {key.key_id}")
    print(f"  owner:      {key.owner}")
    print(f"  scopes:     {','.join(key.scopes) or '(none)'}")
    print(f"  label:      {label_repr}")
    print(f"  created_at: {key.created_at.isoformat()}")
    print(f"  expires_at: {expires_repr}")
    print()
    print("Pass it via the X-API-Key header:")
    print(f"  curl -H 'X-API-Key: {key.plaintext}' http://localhost:8000/v1/agents")


async def _issue(
    owner: str,
    scopes: list[str],
    label: str | None,
    expires_at: datetime | None,
) -> IssuedKey:
    """Open a session, call ``ApiKeyService.create_key``, return result.

    Uses the same async session factory the FastAPI app uses, so the
    CLI honours ``settings.postgres_dsn`` end-to-end.
    """
    async with async_session() as db:
        svc = ApiKeyService(db)
        return await svc.create_key(
            owner=owner,
            scopes=scopes,
            label=label,
            expires_at=expires_at,
        )


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code (0 on success)."""
    owner, scopes, label, expires_at = _resolve_args(argv)
    try:
        issued = asyncio.run(_issue(owner, scopes, label, expires_at))
    except Exception as exc:  # pragma: no cover - exercised manually
        print(f"error: failed to issue key: {exc}", file=sys.stderr)
        return 1
    _print_issued(issued)
    return 0


if __name__ == "__main__":
    sys.exit(main())
