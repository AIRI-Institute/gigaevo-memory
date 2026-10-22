"""Tests for the library-listing index (migration 005, iter #35).

Three layers (mirrors `test_library_metadata.py`):
  1. ORM `Entity.__table__` declares the new partial index with the
     correct column order and ``deleted_at IS NULL`` predicate.
  2. Migration 005 module imports cleanly, has matching revisions, and
     upgrade/downgrade invoke the expected alembic ops.
  3. Sanity check that the existing ``ix_entities_library_listing``
     index from migration 003 is preserved (additive change).
"""

from __future__ import annotations

import importlib.util
import pathlib
from unittest.mock import patch

import pytest

from app.db.models import Entity


# ---------------------------------------------------------------------------
# ORM table metadata
# ---------------------------------------------------------------------------


class TestEntityOrmIndex:
    def test_new_index_declared(self):
        idx_names = {idx.name for idx in Entity.__table__.indexes}
        assert "ix_entities_library_sort" in idx_names

    def test_index_column_order(self):
        """``namespace`` is the equality column; ``last_run_at`` is the
        DESC sort key; ``entity_id`` is the tiebreaker."""
        idx = next(
            i for i in Entity.__table__.indexes
            if i.name == "ix_entities_library_sort"
        )
        names = [c.name if hasattr(c, "name") else str(c) for c in idx.expressions]
        # First column is `namespace`, last is `entity_id`. The middle
        # expression is a `text("last_run_at DESC NULLS LAST")` clause,
        # which SQLAlchemy renders as a literal string when stringified.
        assert names[0] == "namespace"
        assert names[-1] == "entity_id"
        assert "last_run_at" in str(idx.expressions[1])
        assert "DESC NULLS LAST" in str(idx.expressions[1])

    def test_partial_predicate_excludes_soft_deleted(self):
        idx = next(
            i for i in Entity.__table__.indexes
            if i.name == "ix_entities_library_sort"
        )
        # The dialect-specific kwarg lives in `dialect_options` after
        # SQLAlchemy normalises the Index declaration.
        where = idx.dialect_options["postgresql"].get("where")
        assert where is not None
        assert "deleted_at IS NULL" in str(where)

    def test_old_library_index_preserved(self):
        """Migration 005 is purely additive — the iter #11 partial
        index used by `favourites_only` queries must still be there."""
        idx_names = {idx.name for idx in Entity.__table__.indexes}
        assert "ix_entities_library_listing" in idx_names


# ---------------------------------------------------------------------------
# Migration 005 module
# ---------------------------------------------------------------------------


def _load_migration_005():
    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "005_library_listing_index.py"
    )
    spec = importlib.util.spec_from_file_location("mig005", path)
    assert spec is not None and spec.loader is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


@pytest.fixture
def mig005():
    return _load_migration_005()


class TestMigration005:
    def test_revision_chain(self, mig005):
        assert mig005.revision == "005"
        assert mig005.down_revision == "004"

    def test_upgrade_creates_named_index(self, mig005):
        created: list[tuple[str, str, list]] = []

        def _spy_create(name, table, cols, **kw):
            created.append((name, table, list(cols)))

        with patch.object(mig005.op, "create_index", side_effect=_spy_create):
            mig005.upgrade()

        assert len(created) == 1
        name, table, cols = created[0]
        assert name == "ix_entities_library_sort"
        assert table == "entities"
        # First and last columns are bare strings; middle is a TextClause.
        assert cols[0] == "namespace"
        assert "last_run_at" in str(cols[1])
        assert "DESC NULLS LAST" in str(cols[1])
        assert cols[2] == "entity_id"

    def test_upgrade_uses_deleted_at_partial_predicate(self, mig005):
        captured: dict = {}

        def _spy_create(name, table, cols, **kw):
            captured.update(kw)

        with patch.object(mig005.op, "create_index", side_effect=_spy_create):
            mig005.upgrade()

        where = captured.get("postgresql_where")
        assert where is not None
        assert "deleted_at IS NULL" in str(where)

    def test_downgrade_drops_the_index(self, mig005):
        dropped: list[str] = []

        def _spy_drop(name, table_name=""):
            dropped.append(name)

        with patch.object(mig005.op, "drop_index", side_effect=_spy_drop):
            mig005.downgrade()

        assert dropped == ["ix_entities_library_sort"]

    def test_module_is_pure_no_io(self, mig005):
        """upgrade/downgrade should never hit the DB at import time —
        all real work runs through ``alembic.op`` calls, which the
        tests above mock out. Calling both with all alembic ops
        patched must succeed without raising."""
        with patch.object(mig005.op, "create_index"):
            with patch.object(mig005.op, "drop_index"):
                mig005.upgrade()
                mig005.downgrade()
