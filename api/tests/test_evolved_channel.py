"""Tests for the ``evolved`` channel auto-promotion (P2 §5).

The channel rule: pin `evolved` to whichever version has the highest
``evolution_meta.fitness_score`` (falling back to legacy ``fitness``).
First-evolution always pins; ties keep the incumbent (strict ``>``).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import EntityVersion
from app.services.entity_service import EntityService


def _ver(version_id: uuid.UUID, *, evolution_meta: dict | None = None) -> EntityVersion:
    return EntityVersion(
        version_id=version_id,
        entity_id=uuid.uuid4(),
        version_number=0,
        content_json={},
        meta_json={},
        parents=None,
        evolution_meta=evolution_meta,
        author=None,
        created_at=datetime(2026, 5, 16, 12, tzinfo=timezone.utc),
    )


class TestExtractFitness:
    """Canonical fitness extraction prefers `fitness_score`, falls back
    to legacy `fitness`, ignores everything else."""

    def _svc(self) -> EntityService:
        return EntityService(AsyncMock())

    def test_returns_none_when_evolution_meta_missing(self):
        assert self._svc()._extract_fitness(None) is None
        assert self._svc()._extract_fitness({}) is None

    def test_pulls_fitness_score_standardised(self):
        assert self._svc()._extract_fitness({"fitness_score": 0.87}) == 0.87

    def test_falls_back_to_legacy_fitness(self):
        assert self._svc()._extract_fitness({"fitness": 0.5}) == 0.5

    def test_fitness_score_takes_precedence_over_legacy(self):
        """When both shapes are set, the standardised field wins."""
        out = self._svc()._extract_fitness(
            {"fitness_score": 0.9, "fitness": 0.1}
        )
        assert out == 0.9

    def test_unparsable_returns_none(self):
        assert self._svc()._extract_fitness({"fitness_score": "n/a"}) is None
        assert self._svc()._extract_fitness({"fitness_score": [1, 2]}) is None

    def test_coerces_int_to_float(self):
        assert self._svc()._extract_fitness({"fitness_score": 1}) == 1.0


class TestMaybePromoteEvolvedChannel:
    """Service helper picks the channel pin without I/O when possible."""

    @pytest.mark.asyncio
    async def test_no_fitness_is_noop(self):
        svc = EntityService(AsyncMock())
        channels = {"latest": "v0"}
        out = await svc._maybe_promote_evolved_channel(
            channels, uuid.uuid4(), evolution_meta=None
        )
        assert "evolved" not in out
        assert out == channels  # untouched

    @pytest.mark.asyncio
    async def test_first_evolution_pins(self):
        """No `evolved` channel yet → pin to the new version."""
        svc = EntityService(AsyncMock())
        new_id = uuid.uuid4()
        channels = {"latest": "v0"}
        out = await svc._maybe_promote_evolved_channel(
            channels, new_id, {"fitness_score": 0.5}
        )
        assert out["evolved"] == str(new_id)
        # `latest` is unchanged.
        assert out["latest"] == "v0"

    @pytest.mark.asyncio
    async def test_higher_fitness_promotes(self):
        """Current evolved scored 0.5; new version scores 0.8 → promote."""
        current_id = uuid.uuid4()
        current = _ver(current_id, evolution_meta={"fitness_score": 0.5})
        with patch.object(EntityService, "get_version", new=AsyncMock(return_value=current)):
            svc = EntityService(AsyncMock())
            new_id = uuid.uuid4()
            out = await svc._maybe_promote_evolved_channel(
                {"latest": "vN", "evolved": str(current_id)},
                new_id,
                {"fitness_score": 0.8},
            )
            assert out["evolved"] == str(new_id)

    @pytest.mark.asyncio
    async def test_lower_fitness_does_not_demote(self):
        """A new version with worse fitness should NOT replace the pin."""
        current_id = uuid.uuid4()
        current = _ver(current_id, evolution_meta={"fitness_score": 0.9})
        with patch.object(EntityService, "get_version", new=AsyncMock(return_value=current)):
            svc = EntityService(AsyncMock())
            new_id = uuid.uuid4()
            out = await svc._maybe_promote_evolved_channel(
                {"latest": "vN", "evolved": str(current_id)},
                new_id,
                {"fitness_score": 0.3},
            )
            assert out["evolved"] == str(current_id)

    @pytest.mark.asyncio
    async def test_equal_fitness_keeps_incumbent(self):
        """Strict `>` — ties keep the existing pin (no churn on re-runs)."""
        current_id = uuid.uuid4()
        current = _ver(current_id, evolution_meta={"fitness_score": 0.5})
        with patch.object(EntityService, "get_version", new=AsyncMock(return_value=current)):
            svc = EntityService(AsyncMock())
            new_id = uuid.uuid4()
            out = await svc._maybe_promote_evolved_channel(
                {"latest": "vN", "evolved": str(current_id)},
                new_id,
                {"fitness_score": 0.5},
            )
            assert out["evolved"] == str(current_id)

    @pytest.mark.asyncio
    async def test_missing_current_fitness_promotes(self):
        """Incumbent has no fitness → unconditionally promote the new
        version (any score beats no score)."""
        current_id = uuid.uuid4()
        current = _ver(current_id, evolution_meta=None)
        with patch.object(EntityService, "get_version", new=AsyncMock(return_value=current)):
            svc = EntityService(AsyncMock())
            new_id = uuid.uuid4()
            out = await svc._maybe_promote_evolved_channel(
                {"latest": "vN", "evolved": str(current_id)},
                new_id,
                {"fitness_score": 0.1},
            )
            assert out["evolved"] == str(new_id)

    @pytest.mark.asyncio
    async def test_corrupt_pointer_overwrites(self):
        """An unparsable `evolved` pointer is replaced unconditionally."""
        svc = EntityService(AsyncMock())
        new_id = uuid.uuid4()
        out = await svc._maybe_promote_evolved_channel(
            {"latest": "vN", "evolved": "not-a-uuid"},
            new_id,
            {"fitness_score": 0.1},
        )
        assert out["evolved"] == str(new_id)

    @pytest.mark.asyncio
    async def test_missing_version_overwrites(self):
        """Pinned UUID resolves to None → promote new."""
        current_id = uuid.uuid4()
        with patch.object(EntityService, "get_version", new=AsyncMock(return_value=None)):
            svc = EntityService(AsyncMock())
            new_id = uuid.uuid4()
            out = await svc._maybe_promote_evolved_channel(
                {"latest": "vN", "evolved": str(current_id)},
                new_id,
                {"fitness_score": 0.1},
            )
            assert out["evolved"] == str(new_id)

    @pytest.mark.asyncio
    async def test_legacy_fitness_drives_promotion(self):
        """Legacy `fitness` field alone is enough to drive the channel pin."""
        svc = EntityService(AsyncMock())
        new_id = uuid.uuid4()
        out = await svc._maybe_promote_evolved_channel(
            {"latest": "v0"}, new_id, {"fitness": 0.42}
        )
        assert out["evolved"] == str(new_id)


class TestCreateEntityPinsEvolved:
    """End-to-end: `create_entity` calls into the promotion helper."""

    @pytest.mark.asyncio
    async def test_create_with_fitness_pins_evolved(self):
        """A first-version create that carries fitness sets the
        `evolved` channel alongside `latest`."""
        added = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=added.append)
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch(
            "app.services.entity_service.sync_entity_search_documents",
            new_callable=AsyncMock,
        ), patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ):
            svc = EntityService(db)
            entity, version = await svc.create_entity(
                entity_type_plural="chains",
                name="evolved-chain",
                content={},
                evolution_meta={"fitness_score": 0.71, "generation": 1},
            )

        # Two channels now: latest + evolved, both pointing at v0.
        assert entity.channels["latest"] == str(version.version_id)
        assert entity.channels["evolved"] == str(version.version_id)

    @pytest.mark.asyncio
    async def test_create_without_fitness_no_evolved_channel(self):
        added = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=added.append)
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch(
            "app.services.entity_service.sync_entity_search_documents",
            new_callable=AsyncMock,
        ), patch(
            "app.services.entity_service.publish_entity_event",
            new_callable=AsyncMock,
        ):
            svc = EntityService(db)
            entity, _ = await svc.create_entity(
                entity_type_plural="chains",
                name="ordinary-chain",
                content={},
            )

        # No fitness → no `evolved` channel.
        assert "evolved" not in entity.channels
        assert "latest" in entity.channels
