"""Tests for CARE library-mutation service methods + agents-router endpoints.

Three layers:
  1. ``EntityService.set_favourite`` / ``record_run`` / ``update_metadata``
     against a mocked DB session.
  2. ``entity_metadata_kwargs`` helper return shape.
  3. ``agents`` router exposes the new endpoints + the existing
     responses now surface the 5 library-metadata fields via the shared
     helper.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Entity
from app.services.entity_service import EntityService, entity_metadata_kwargs


@pytest.fixture(autouse=True)
def _silence_event_publisher():
    """Stub out ``publish_entity_event`` so service-layer tests don't
    require a live Redis. Each library-mutation method now publishes
    an event (iter #16 §6 audit); these tests are uninterested in
    that side-effect.
    """
    with patch(
        "app.services.entity_service.publish_entity_event",
        new_callable=AsyncMock,
    ):
        yield


def _stub_entity(**overrides) -> Entity:
    """Build an in-memory Entity instance (no DB)."""
    base = dict(
        entity_id=uuid.uuid4(),
        entity_type="agent",
        namespace="glazkov",
        name="financier",
        tags=[],
        when_to_use=None,
        channels={"latest": str(uuid.uuid4())},
        deleted_at=None,
        favourite=False,
        run_count=0,
        last_run_at=None,
        display_name="financier",
        description=None,
    )
    base.update(overrides)
    return Entity(**base)


def _mock_db_returning(entity: Entity | None) -> AsyncMock:
    """Build an AsyncSession mock whose `.execute(...).scalar_one_or_none()` returns `entity`."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=entity)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestEntityMetadataKwargs:
    """The router helper returns the five fields with safe coercions."""

    def test_returns_five_fields(self):
        entity = _stub_entity()
        out = entity_metadata_kwargs(entity)
        assert set(out.keys()) == {
            "favourite",
            "run_count",
            "last_run_at",
            "display_name",
            "description",
        }

    def test_coerces_favourite_to_bool(self):
        entity = _stub_entity(favourite=True)
        assert entity_metadata_kwargs(entity)["favourite"] is True

    def test_coerces_run_count_to_int_with_none_safe_default(self):
        entity = _stub_entity()
        entity.run_count = None  # type: ignore[assignment]
        assert entity_metadata_kwargs(entity)["run_count"] == 0


class TestSetFavourite:
    @pytest.mark.asyncio
    async def test_set_favourite_true_updates_entity(self):
        entity = _stub_entity(favourite=False)
        db = _mock_db_returning(entity)

        svc = EntityService(db)
        out = await svc.set_favourite(entity.entity_id, value=True)

        assert out is entity
        assert entity.favourite is True
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(entity)

    @pytest.mark.asyncio
    async def test_set_favourite_false_toggles_off(self):
        entity = _stub_entity(favourite=True)
        db = _mock_db_returning(entity)

        svc = EntityService(db)
        out = await svc.set_favourite(entity.entity_id, value=False)

        assert out is entity
        assert entity.favourite is False

    @pytest.mark.asyncio
    async def test_set_favourite_returns_none_for_missing(self):
        db = _mock_db_returning(None)
        svc = EntityService(db)
        out = await svc.set_favourite(uuid.uuid4(), value=True)
        assert out is None
        db.commit.assert_not_awaited()


class TestRecordRun:
    @pytest.mark.asyncio
    async def test_record_run_bumps_count_and_timestamp(self):
        entity = _stub_entity(run_count=3, last_run_at=None)
        db = _mock_db_returning(entity)

        svc = EntityService(db)
        before = datetime.now(timezone.utc)
        out = await svc.record_run(entity.entity_id)
        after = datetime.now(timezone.utc)

        assert out is entity
        assert entity.run_count == 4
        # last_run_at sits between `before` and `after`.
        assert entity.last_run_at is not None
        assert before <= entity.last_run_at <= after
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_run_handles_null_starting_count(self):
        entity = _stub_entity()
        entity.run_count = None  # type: ignore[assignment]
        db = _mock_db_returning(entity)

        svc = EntityService(db)
        await svc.record_run(entity.entity_id)
        assert entity.run_count == 1  # None coerced to 0, then +1

    @pytest.mark.asyncio
    async def test_record_run_returns_none_for_missing(self):
        db = _mock_db_returning(None)
        svc = EntityService(db)
        out = await svc.record_run(uuid.uuid4())
        assert out is None
        db.commit.assert_not_awaited()


class TestUpdateMetadata:
    @pytest.mark.asyncio
    async def test_update_metadata_partial(self):
        """Each kwarg only mutates when explicitly provided."""
        entity = _stub_entity(
            display_name="old",
            description="old desc",
            tags=["pdf"],
            favourite=False,
        )
        db = _mock_db_returning(entity)

        svc = EntityService(db)
        out = await svc.update_metadata(
            entity.entity_id,
            display_name="new",
            favourite=True,
            # description / tags omitted → preserved
        )

        assert out is entity
        assert entity.display_name == "new"
        assert entity.favourite is True
        assert entity.description == "old desc"
        assert entity.tags == ["pdf"]

    @pytest.mark.asyncio
    async def test_update_metadata_truncates_display_name(self):
        entity = _stub_entity(display_name="old")
        db = _mock_db_returning(entity)

        svc = EntityService(db)
        await svc.update_metadata(entity.entity_id, display_name="x" * 350)
        assert entity.display_name == "x" * 200  # VARCHAR(200) cap

    @pytest.mark.asyncio
    async def test_update_metadata_accepts_empty_tags_list(self):
        """Setting tags=[] explicitly clears them (distinct from omitting)."""
        entity = _stub_entity(tags=["pdf", "extraction"])
        db = _mock_db_returning(entity)

        svc = EntityService(db)
        await svc.update_metadata(entity.entity_id, tags=[])
        assert entity.tags == []

    @pytest.mark.asyncio
    async def test_update_metadata_returns_none_for_missing(self):
        db = _mock_db_returning(None)
        svc = EntityService(db)
        out = await svc.update_metadata(uuid.uuid4(), display_name="x")
        assert out is None
        db.commit.assert_not_awaited()


class TestAgentsRouterRegistration:
    """The new endpoints are registered on the agents router."""

    def test_router_has_patch_and_mutation_routes(self):
        from app.routers.agents import router

        paths_methods = {
            (route.path, method)
            for route in router.routes
            for method in getattr(route, "methods", ())
        }
        assert ("/v1/agents/{agent_id}", "PATCH") in paths_methods
        assert ("/v1/agents/{agent_id}/favourite", "POST") in paths_methods
        assert ("/v1/agents/{agent_id}/run-recorded", "POST") in paths_methods

    def test_openapi_lists_new_endpoints(self):
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/v1/agents/{agent_id}" in paths
        assert "patch" in paths["/v1/agents/{agent_id}"]
        assert "/v1/agents/{agent_id}/favourite" in paths
        assert "/v1/agents/{agent_id}/run-recorded" in paths

    def test_request_models_exposed_in_openapi_schema(self):
        from app.main import app

        components = app.openapi()["components"]["schemas"]
        assert "EntityPatchRequest" in components
        assert "FavouriteRequest" in components
        assert "RecordRunRequest" in components

    def test_response_helper_surfaces_library_fields(self):
        """`_agent_response` plumbs the 5 fields from the entity."""
        from app.routers.agents import _agent_response

        entity = _stub_entity(
            favourite=True,
            run_count=12,
            last_run_at=datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc),
            display_name="Financier helper",
            description="Drafts monthly reports.",
        )
        version = MagicMock(
            version_id=uuid.uuid4(),
            content_json={"goal": "draft reports"},
            meta_json={"author": "mage"},
        )
        resp = _agent_response(entity, version, channel="latest")

        assert resp.favourite is True
        assert resp.run_count == 12
        assert resp.last_run_at == datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc)
        assert resp.display_name == "Financier helper"
        assert resp.description == "Drafts monthly reports."
        # ETag computed from content; meta passed through.
        assert resp.etag
        assert resp.meta == {"author": "mage"}
