"""API-key service: create / verify / revoke / list (P1 §3).

API keys are issued as opaque 32-byte tokens encoded as URL-safe
base64 strings. Only the **SHA-256 hash** is persisted; the plaintext
is returned exactly once at creation time, and re-hashed on every
verification round-trip.

Verification semantics:
    * The header value is hashed with the same algorithm.
    * The hash is looked up in ``api_keys.key_hash``.
    * Expiry (``expires_at <= now``) and revocation (``revoked_at IS
      NOT NULL``) cause the lookup to return ``None``.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ApiKey


def _hash_key(plaintext: str) -> str:
    """SHA-256 hex digest of the plaintext key string.

    Pure function (no DB I/O). Exposed so the test suite + CLI can
    compute hashes the same way the service does.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_key() -> str:
    """Generate a fresh plaintext API key: 32 URL-safe bytes ≈ 43 chars."""
    return secrets.token_urlsafe(32)


@dataclass
class IssuedKey:
    """Result of ``ApiKeyService.create_key``.

    Carries the **plaintext** token (the only time the caller will
    ever see it) plus the new row's metadata. Treat ``plaintext`` as
    a secret — log it once for the caller, never persist server-side.
    """

    plaintext: str
    key_id: uuid.UUID
    owner: str
    scopes: list[str]
    label: str | None
    created_at: datetime
    expires_at: datetime | None


class ApiKeyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_key(
        self,
        *,
        owner: str,
        scopes: list[str] | None = None,
        label: str | None = None,
        expires_at: datetime | None = None,
    ) -> IssuedKey:
        """Issue a new API key for ``owner`` with optional ``scopes``.

        Returns an :class:`IssuedKey` carrying the plaintext token —
        the caller MUST persist this themselves (e.g. write it to a
        secrets manager). After this call returns, the plaintext can
        never be recovered from the database.

        ``expires_at`` defaults to None (never expires).
        """
        plaintext = _generate_key()
        key_hash = _hash_key(plaintext)
        row = ApiKey(
            key_id=uuid.uuid4(),
            key_hash=key_hash,
            owner=owner,
            label=label,
            scopes=list(scopes or []),
            expires_at=expires_at,
            revoked_at=None,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return IssuedKey(
            plaintext=plaintext,
            key_id=row.key_id,
            owner=row.owner,
            scopes=list(row.scopes or []),
            label=row.label,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )

    async def verify_key(self, plaintext: str) -> ApiKey | None:
        """Look up a row by hashing ``plaintext``. Returns ``None``
        when the key is unknown, expired, or revoked.

        Constant-time-ish: SHA-256 + index lookup, no length-dependent
        early returns on the hot path.
        """
        if not plaintext:
            return None
        key_hash = _hash_key(plaintext)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if row.revoked_at is not None:
            return None
        if row.expires_at is not None and row.expires_at <= datetime.now(timezone.utc):
            return None
        return row

    async def revoke_key(self, key_id: uuid.UUID) -> bool:
        """Mark a key as revoked. Returns True if the row existed and
        was newly revoked; False if missing or already revoked.
        """
        stmt = select(ApiKey).where(ApiKey.key_id == key_id)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    async def list_keys(
        self,
        *,
        owner: str | None = None,
        include_revoked: bool = False,
    ) -> list[ApiKey]:
        """List keys, optionally filtered by owner.

        ``include_revoked=False`` (default) hides revoked rows — the
        common case for "show this principal's active keys".
        """
        stmt = select(ApiKey)
        if owner is not None:
            stmt = stmt.where(ApiKey.owner == owner)
        if not include_revoked:
            stmt = stmt.where(ApiKey.revoked_at.is_(None))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
