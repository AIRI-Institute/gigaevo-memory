"""Add CARE library metadata to entities.

Denormalises the fields the CARE TUI "My Agents" library uses for
sorting / filtering / favouriting:

  * ``favourite``     — boolean, indexed, default false.
  * ``run_count``     — integer, default 0.
  * ``last_run_at``   — timestamptz, indexed, nullable.
  * ``display_name``  — varchar(200), nullable; CARE-editable name
                         distinct from the URL-safe ``name`` column.
  * ``description``   — text, nullable; free-form user description
                         distinct from auto-generated ``when_to_use``.

Backfill on upgrade: ``last_run_at`` ← ``MAX(entity_versions.created_at)``
per entity (so existing chains immediately sort by "recency"), and
``display_name`` ← ``name`` so the library renders without empty cells.

Also adds a composite index ``(namespace, favourite, last_run_at)``
under the ``deleted_at IS NULL`` partial predicate to keep library
listing fast at 10k+ entities.

Revision ID: 003
Revises: 002
Create Date: 2026-05-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column(
            "favourite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "entities",
        sa.Column(
            "run_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "entities",
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "entities",
        sa.Column(
            "display_name",
            sa.String(length=200),
            nullable=True,
        ),
    )
    op.add_column(
        "entities",
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
    )

    # Backfill: pre-existing rows get sensible defaults so the CARE
    # library renders something on day-one of the migration.
    op.execute(
        """
        UPDATE entities
        SET display_name = name
        WHERE display_name IS NULL
        """
    )
    op.execute(
        """
        UPDATE entities e
        SET last_run_at = sub.max_created_at
        FROM (
            SELECT entity_id, MAX(created_at) AS max_created_at
            FROM entity_versions
            GROUP BY entity_id
        ) sub
        WHERE e.entity_id = sub.entity_id
          AND e.last_run_at IS NULL
        """
    )

    op.create_index(
        "ix_entities_favourite",
        "entities",
        ["favourite"],
    )
    op.create_index(
        "ix_entities_last_run_at",
        "entities",
        ["last_run_at"],
    )
    # Partial composite index matching the library list query shape:
    #   WHERE namespace = ? AND deleted_at IS NULL
    #   ORDER BY favourite DESC, last_run_at DESC NULLS LAST
    op.create_index(
        "ix_entities_library_listing",
        "entities",
        ["namespace", "favourite", "last_run_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_entities_library_listing", table_name="entities")
    op.drop_index("ix_entities_last_run_at", table_name="entities")
    op.drop_index("ix_entities_favourite", table_name="entities")
    op.drop_column("entities", "description")
    op.drop_column("entities", "display_name")
    op.drop_column("entities", "last_run_at")
    op.drop_column("entities", "run_count")
    op.drop_column("entities", "favourite")
