"""Add `api_keys` table for API-key authentication (P1 §3).

Stores **hashes** of API keys (SHA-256 hex), never the plaintext. The
service layer issues a plaintext token once at creation time and the
caller stores it; subsequent verification re-hashes the incoming
`X-API-Key` header and looks up the row.

Columns:
    key_id      — UUID primary key.
    key_hash    — SHA-256 hex digest of the plaintext key. Unique
                  + indexed for the lookup hot path.
    owner       — Free-form identifier for the principal the key
                  belongs to (e.g. `"glazkov"`). Indexed for
                  listing-by-owner queries.
    label       — Optional human-readable label
                  (e.g. `"CARE laptop dev key"`).
    scopes      — JSONB array of permission strings
                  (`"read:any"`, `"write:agent_skill"`, `"evolve"`, …).
    created_at  — Timestamp the key was issued.
    expires_at  — Optional expiry (NULL = never expires).
    revoked_at  — Set when the key was revoked
                  (`ApiKeyService.revoke_key`). NULL = active.

Revision ID: 004
Revises: 003
Create Date: 2026-05-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("key_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("scopes", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_owner", "api_keys", ["owner"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_owner", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
