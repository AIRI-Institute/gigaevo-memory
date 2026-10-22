"""Tests that library-mutation service methods publish Redis pub/sub events.

The §6 audit revealed that ``set_favourite`` / ``record_run`` /
``update_metadata`` (added in iteration #7) never called
``publish_entity_event``, so CARE's library-screen SSE subscription
would miss every favourite-toggle / run-record / rename.

Each test mocks ``publish_entity_event`` to capture the call arguments
without needing a real Redis instance.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Entity
from app.services.entity_service import EntityService


def _stub_entity(**overrides) -> Entity:
    base = dict(
        entity_id=uuid.uuid4(),
        entity_type="agent",
        namespace="glazkov",
        name="x",
        tags=[],
        when_to_use=None,
        channels={"latest": str(uuid.uuid4())},
        deleted_at=None,
        favourite=False,
        run_count=0,
        last_run_at=None,
        display_name="x",
        description=None,
    )
    base.update(overrides)
    return Entity(**base)


def _mock_db_returning(entity: Entity | None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=entity)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestSetFavouriteEvents:
    @pytest.mark.asyncio
    async def test_publishes_favourite_toggled_on_success(self):
        entity = _stub_entity(favourite=False)
        db = _mock_db_returning(entity)

        with patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ) as pub:
            svc = EntityService(db)
            await svc.set_favourite(entity.entity_id, value=True)

        pub.assert_awaited_once_with(
            "favourite_toggled",
            str(entity.entity_id),
            "agent",
            namespace="glazkov",
            tags=[],
        )

    @pytest.mark.asyncio
    async def test_does_not_publish_when_entity_missing(self):
        db = _mock_db_returning(None)

        with patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ) as pub:
            svc = EntityService(db)
            out = await svc.set_favourite(uuid.uuid4(), value=True)

        assert out is None
        pub.assert_not_awaited()


class TestRecordRunEvents:
    @pytest.mark.asyncio
    async def test_publishes_run_recorded_on_success(self):
        entity = _stub_entity(entity_type="chain", run_count=4)
        db = _mock_db_returning(entity)

        with patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ) as pub:
            svc = EntityService(db)
            await svc.record_run(entity.entity_id, run_id="run-1")

        pub.assert_awaited_once_with(
            "run_recorded",
            str(entity.entity_id),
            "chain",
            namespace="glazkov",
            tags=[],
        )

    @pytest.mark.asyncio
    async def test_passes_through_each_entity_type(self):
        """event payload carries the entity's actual type, not a default."""
        for etype in ("agent", "chain", "agent_skill", "memory_card", "step"):
            entity = _stub_entity(entity_type=etype)
            db = _mock_db_returning(entity)
            with patch(
                "app.services.entity_service.publish_entity_event",
                new_callable=AsyncMock,
            ) as pub:
                svc = EntityService(db)
                await svc.record_run(entity.entity_id)
            pub.assert_awaited_once()
            assert pub.await_args.args[2] == etype


class TestUpdateMetadataEvents:
    @pytest.mark.asyncio
    async def test_publishes_metadata_updated_when_any_field_changes(self):
        entity = _stub_entity()
        db = _mock_db_returning(entity)

        with patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ) as pub:
            svc = EntityService(db)
            await svc.update_metadata(entity.entity_id, display_name="new")

        pub.assert_awaited_once_with(
            "metadata_updated",
            str(entity.entity_id),
            "agent",
            namespace="glazkov",
            tags=[],
        )

    @pytest.mark.asyncio
    async def test_publishes_once_even_when_multiple_fields_change(self):
        entity = _stub_entity()
        db = _mock_db_returning(entity)

        with patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ) as pub:
            svc = EntityService(db)
            await svc.update_metadata(
                entity.entity_id,
                display_name="new",
                description="d",
                tags=["a"],
                favourite=True,
            )

        # Single event regardless of how many fields the PATCH touched.
        # The publisher reads `entity.tags` after the mutation, so the
        # post-PATCH `["a"]` lands in the event payload.
        pub.assert_awaited_once_with(
            "metadata_updated",
            str(entity.entity_id),
            "agent",
            namespace="glazkov",
            tags=["a"],
        )

    @pytest.mark.asyncio
    async def test_no_publish_when_no_kwargs_provided(self):
        """All-None PATCH is a no-op the library shouldn't react to."""
        entity = _stub_entity()
        db = _mock_db_returning(entity)

        with patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ) as pub:
            svc = EntityService(db)
            await svc.update_metadata(entity.entity_id)

        pub.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_publish_when_entity_missing(self):
        db = _mock_db_returning(None)

        with patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ) as pub:
            svc = EntityService(db)
            await svc.update_metadata(uuid.uuid4(), display_name="x")

        pub.assert_not_awaited()


class TestEventTypesAreDistinct:
    """Each library mutation publishes a unique event_type so the CARE
    library can discriminate between favourite-toggle / run-record /
    rename without inspecting the entity diff."""

    @pytest.mark.asyncio
    async def test_event_types_distinct(self):
        seen: set[str] = set()
        for setup, action in [
            (lambda e: None, lambda svc, e: svc.set_favourite(e.entity_id, value=True)),
            (lambda e: None, lambda svc, e: svc.record_run(e.entity_id)),
            (lambda e: None,
             lambda svc, e: svc.update_metadata(e.entity_id, display_name="x")),
        ]:
            entity = _stub_entity()
            db = _mock_db_returning(entity)
            with patch(
                "app.services.entity_service.publish_entity_event",
                new_callable=AsyncMock,
            ) as pub:
                svc = EntityService(db)
                await action(svc, entity)
            seen.add(pub.await_args.args[0])
        assert seen == {"favourite_toggled", "run_recorded", "metadata_updated"}
