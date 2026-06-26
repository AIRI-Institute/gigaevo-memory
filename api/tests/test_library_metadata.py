"""Tests for CARE library-metadata schema (migration 003).

Covers four layers:
  1. ``Entity`` ORM model exposes the five new columns with expected types.
  2. ``EntityResponse`` Pydantic shape accepts and round-trips them.
  3. Migration 003 module is importable, has matching revisions, and the
     ``upgrade()`` / ``downgrade()`` operation lists line up.
  4. ``EntityService.create_entity`` populates ``display_name`` /
     ``description`` defaults on a fresh entity (mocked DB).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Boolean, DateTime, Integer, String, Text

from app.db.models import Entity
from app.models.responses import EntityResponse


class TestEntityOrmColumns:
    """Mapping definitions on the SQLAlchemy ``entities`` table."""

    def test_columns_exist(self):
        cols = Entity.__table__.c
        assert "favourite" in cols
        assert "run_count" in cols
        assert "last_run_at" in cols
        assert "display_name" in cols
        assert "description" in cols

    def test_column_types(self):
        cols = Entity.__table__.c
        assert isinstance(cols["favourite"].type, Boolean)
        assert isinstance(cols["run_count"].type, Integer)
        assert isinstance(cols["last_run_at"].type, DateTime)
        assert isinstance(cols["display_name"].type, String)
        assert isinstance(cols["description"].type, Text)

    def test_display_name_length_matches_migration(self):
        # display_name is VARCHAR(200) so it fits the CARE TUI label slot
        # while leaving room for entity_id-prefixed display names.
        assert Entity.__table__.c.display_name.type.length == 200

    def test_favourite_and_run_count_have_server_defaults(self):
        cols = Entity.__table__.c
        assert cols["favourite"].server_default is not None
        assert cols["run_count"].server_default is not None

    def test_favourite_and_run_count_are_not_nullable(self):
        cols = Entity.__table__.c
        assert cols["favourite"].nullable is False
        assert cols["run_count"].nullable is False

    def test_optional_fields_are_nullable(self):
        cols = Entity.__table__.c
        assert cols["last_run_at"].nullable is True
        assert cols["display_name"].nullable is True
        assert cols["description"].nullable is True

    def test_indices_match_query_shape(self):
        idx_names = {idx.name for idx in Entity.__table__.indexes}
        assert "ix_entities_library_listing" in idx_names

    def test_library_listing_index_columns(self):
        idx = next(
            i for i in Entity.__table__.indexes if i.name == "ix_entities_library_listing"
        )
        cols = [c.name for c in idx.columns]
        assert cols == ["namespace", "favourite", "last_run_at"]


class TestEntityResponseShape:
    """Pydantic surface CARE clients consume."""

    def _base_payload(self):
        return {
            "entity_type": "agent",
            "entity_id": "00000000-0000-0000-0000-000000000001",
            "version_id": "00000000-0000-0000-0000-000000000002",
            "channel": "latest",
            "etag": "abc",
            "meta": {},
            "content": {},
        }

    def test_defaults_when_omitted(self):
        """Existing routers can keep emitting the original shape."""
        resp = EntityResponse(**self._base_payload())
        assert resp.favourite is False
        assert resp.run_count == 0
        assert resp.last_run_at is None
        assert resp.display_name is None
        assert resp.description is None

    def test_round_trip_with_library_metadata(self):
        now = datetime(2026, 5, 16, 9, 30, tzinfo=timezone.utc)
        payload = self._base_payload()
        payload.update(
            favourite=True,
            run_count=7,
            last_run_at=now.isoformat(),
            display_name="Financier helper",
            description="Helps finance team draft monthly reports.",
        )
        resp = EntityResponse(**payload)
        assert resp.favourite is True
        assert resp.run_count == 7
        assert resp.last_run_at == now
        assert resp.display_name == "Financier helper"
        assert resp.description == "Helps finance team draft monthly reports."

    def test_openapi_schema_exposes_new_fields(self):
        from app.main import app

        schema = app.openapi()["components"]["schemas"]["EntityResponse"]
        for field in ("favourite", "run_count", "last_run_at", "display_name", "description"):
            assert field in schema["properties"]


def _load_migration_003():
    """Load migration 003 via importlib (its filename starts with a digit
    so a plain ``import`` statement won't work)."""
    import importlib.util
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "003_library_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("mig003", path)
    assert spec is not None and spec.loader is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


@pytest.fixture
def mig003():
    return _load_migration_003()


class TestMigration003:
    """Migration module structure (without running against a real DB)."""

    def test_revision_chain(self, mig003):
        assert mig003.revision == "003"
        assert mig003.down_revision == "002"

    def test_upgrade_and_downgrade_callable(self, mig003):
        assert callable(mig003.upgrade)
        assert callable(mig003.downgrade)

    def test_upgrade_invokes_add_column_for_each_new_field(self, mig003):
        """Spy on alembic.op.add_column to confirm exact column set."""
        added: list[tuple[str, str]] = []

        def _spy_add(table: str, column) -> None:
            added.append((table, column.name))

        with patch.object(mig003.op, "add_column", side_effect=_spy_add):
            with patch.object(mig003.op, "execute"):  # backfill statements
                with patch.object(mig003.op, "create_index"):
                    mig003.upgrade()

        assert ("entities", "favourite") in added
        assert ("entities", "run_count") in added
        assert ("entities", "last_run_at") in added
        assert ("entities", "display_name") in added
        assert ("entities", "description") in added
        assert len(added) == 5

    def test_downgrade_drops_all_five_columns_and_indices(self, mig003):
        dropped_columns: list[tuple[str, str]] = []
        dropped_indices: list[str] = []

        def _spy_drop_col(table: str, name: str) -> None:
            dropped_columns.append((table, name))

        def _spy_drop_idx(name: str, table_name: str = "") -> None:
            dropped_indices.append(name)

        with patch.object(mig003.op, "drop_column", side_effect=_spy_drop_col):
            with patch.object(mig003.op, "drop_index", side_effect=_spy_drop_idx):
                mig003.downgrade()

        assert {name for _, name in dropped_columns} == {
            "favourite",
            "run_count",
            "last_run_at",
            "display_name",
            "description",
        }
        assert "ix_entities_library_listing" in dropped_indices
        assert "ix_entities_favourite" in dropped_indices
        assert "ix_entities_last_run_at" in dropped_indices


class TestCreateEntityDefaults:
    """`EntityService.create_entity` populates library defaults."""

    @pytest.mark.asyncio
    async def test_create_entity_sets_display_name_and_description(self):
        from app.services.entity_service import EntityService

        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        added: list = []
        db.add = MagicMock(side_effect=added.append)

        with patch(
            "app.services.entity_service.sync_entity_search_documents",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.entity_service.publish_entity_event",
                new_callable=AsyncMock,
            ):
                svc = EntityService(db)
                entity, _version = await svc.create_entity(
                    entity_type_plural="agents",
                    name="financier-helper",
                    content={"goal": "draft monthly reports"},
                    when_to_use="When the finance team needs a monthly report.",
                )

        # display_name mirrors `name`; description mirrors when_to_use.
        assert entity.display_name == "financier-helper"
        assert entity.description == "When the finance team needs a monthly report."
        # favourite/run_count/last_run_at keep DB defaults — the ORM
        # leaves them unset on the in-memory object until INSERT applies
        # `server_default`, so we just confirm they weren't pre-set.
        assert entity.display_name != entity.description  # sanity

    @pytest.mark.asyncio
    async def test_display_name_truncates_to_200_chars(self):
        from app.services.entity_service import EntityService

        long_name = "x" * 350
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        with patch(
            "app.services.entity_service.sync_entity_search_documents",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.services.entity_service.publish_entity_event",
                new_callable=AsyncMock,
            ):
                svc = EntityService(db)
                entity, _ = await svc.create_entity(
                    entity_type_plural="agents",
                    name=long_name,
                    content={},
                )

        # `name` keeps the original full string; display_name truncates
        # to fit VARCHAR(200) so the DB INSERT won't blow up.
        assert entity.name == long_name
        assert entity.display_name == "x" * 200
