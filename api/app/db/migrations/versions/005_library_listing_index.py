"""Library listing index: match the CARE library ORDER BY shape.

Iter #35 follow-up to migration 003 (which shipped a composite index
on ``(namespace, favourite, last_run_at)`` without explicit sort
direction).

The actual query in :meth:`EntityService.list_entities` is::

    WHERE entity_type = ?
      AND deleted_at IS NULL
      AND channels ? :channel
      AND namespace = ?           -- when filtering by namespace
    ORDER BY last_run_at DESC NULLS LAST, entity_id ASC
    LIMIT N

The CARE TUI library default sort surfaces ``last_run_at DESC NULLS LAST``
under a namespace filter — never ``favourite`` in the ORDER BY (the
``favourites_only`` knob is a WHERE filter, not a sort key). The new
partial index aligns its column order with the planner's preferred
scan direction so a paginated listing under 10k+ entities reads a
narrow range of the index rather than scanning + sorting.

``favourites_only=TRUE`` queries are already covered by the standalone
``ix_entities_favourite`` index from migration 003. The GIN index on
``tags`` (``ix_entities_tags``, migration 001) already supports the
``tags ?& '{...}'`` filter from the same listing endpoint, so no new
GIN work is needed here.

Revision ID: 005
Revises: 004
Create Date: 2026-05-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Match the planner's preferred scan direction for the library
    # default sort. ``entity_id ASC`` is the tiebreaker for stable
    # pagination at identical ``last_run_at`` values.
    op.create_index(
        "ix_entities_library_sort",
        "entities",
        [
            "namespace",
            sa.text("last_run_at DESC NULLS LAST"),
            "entity_id",
        ],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_entities_library_sort", table_name="entities")
