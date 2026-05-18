"""Tests for the events firehose filter logic + enriched payload.

Iteration #17 §6 P1: added ``tags`` and ``event_type`` query params to
``/v1/events/stream`` and ``namespace``/``tags`` to the published
payload. These tests cover both the filter predicate and the publisher
shape — without spinning up a real Redis.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.events.publisher import publish_entity_event
from app.routers.events import _event_passes_filters


# ---------------------------------------------------------------------------
# Filter predicate — pure function, no I/O
# ---------------------------------------------------------------------------


def _evt(**ov) -> dict:
    base = {
        "event_type": "run_recorded",
        "entity_id": "agent-001",
        "entity_type": "agent",
        "version_id": None,
        "channel": "latest",
        "namespace": "glazkov",
        "tags": ["finance", "monthly"],
        "timestamp": "2026-05-16T12:00:00+00:00",
    }
    base.update(ov)
    return base


class TestFilterPredicate:
    def test_no_filters_lets_everything_through(self):
        assert _event_passes_filters(
            _evt(),
            entity_type=None,
            entity_id=None,
            namespace=None,
            tags=None,
            event_type=None,
        ) is True

    def test_entity_type_mismatch_rejects(self):
        assert _event_passes_filters(
            _evt(entity_type="chain"),
            entity_type="agent",
            entity_id=None, namespace=None, tags=None, event_type=None,
        ) is False

    def test_entity_id_mismatch_rejects(self):
        assert _event_passes_filters(
            _evt(),
            entity_type=None,
            entity_id="other-id",
            namespace=None, tags=None, event_type=None,
        ) is False

    def test_namespace_mismatch_rejects(self):
        assert _event_passes_filters(
            _evt(namespace="alice"),
            entity_type=None, entity_id=None,
            namespace="glazkov",
            tags=None, event_type=None,
        ) is False

    def test_event_type_filter(self):
        assert _event_passes_filters(
            _evt(event_type="run_recorded"),
            entity_type=None, entity_id=None, namespace=None,
            tags=None, event_type="run_recorded",
        ) is True
        assert _event_passes_filters(
            _evt(event_type="metadata_updated"),
            entity_type=None, entity_id=None, namespace=None,
            tags=None, event_type="run_recorded",
        ) is False


class TestTagsFilter:
    def test_intersection_lets_through(self):
        """Event tagged [finance, monthly]; subscriber wants [monthly]."""
        assert _event_passes_filters(
            _evt(tags=["finance", "monthly"]),
            entity_type=None, entity_id=None, namespace=None,
            tags=["monthly"], event_type=None,
        ) is True

    def test_or_within_tag_set(self):
        """Subscriber wants ANY of [pdf, monthly] — event has just [monthly]."""
        assert _event_passes_filters(
            _evt(tags=["monthly"]),
            entity_type=None, entity_id=None, namespace=None,
            tags=["pdf", "monthly"], event_type=None,
        ) is True

    def test_no_overlap_rejects(self):
        assert _event_passes_filters(
            _evt(tags=["weekly"]),
            entity_type=None, entity_id=None, namespace=None,
            tags=["monthly"], event_type=None,
        ) is False

    def test_empty_event_tags_with_non_empty_filter_rejects(self):
        """Untagged events never satisfy a non-empty tag filter."""
        assert _event_passes_filters(
            _evt(tags=[]),
            entity_type=None, entity_id=None, namespace=None,
            tags=["monthly"], event_type=None,
        ) is False

    def test_missing_tags_field_treated_as_empty(self):
        evt = _evt()
        evt.pop("tags")
        assert _event_passes_filters(
            evt,
            entity_type=None, entity_id=None, namespace=None,
            tags=["monthly"], event_type=None,
        ) is False


class TestAllFiltersCombined:
    def test_all_match_passes(self):
        assert _event_passes_filters(
            _evt(),
            entity_type="agent",
            entity_id="agent-001",
            namespace="glazkov",
            tags=["finance"],
            event_type="run_recorded",
        ) is True

    def test_any_mismatch_rejects(self):
        # entity_type matches, but event_type doesn't.
        assert _event_passes_filters(
            _evt(event_type="metadata_updated"),
            entity_type="agent",
            entity_id="agent-001",
            namespace="glazkov",
            tags=["finance"],
            event_type="run_recorded",
        ) is False


# ---------------------------------------------------------------------------
# Publisher — payload shape
# ---------------------------------------------------------------------------


class TestPublisherPayload:
    @pytest.mark.asyncio
    async def test_namespace_and_tags_included(self):
        captured: list[str] = []

        class _FakeRedis:
            async def publish(self, channel: str, payload: str):
                captured.append(payload)

        with patch("app.events.publisher.get_redis", new=AsyncMock(return_value=_FakeRedis())):
            await publish_entity_event(
                "run_recorded",
                "agent-001",
                "agent",
                namespace="glazkov",
                tags=["finance", "monthly"],
            )

        assert len(captured) == 1
        import json
        evt = json.loads(captured[0])
        assert evt["event_type"] == "run_recorded"
        assert evt["entity_id"] == "agent-001"
        assert evt["entity_type"] == "agent"
        assert evt["namespace"] == "glazkov"
        assert evt["tags"] == ["finance", "monthly"]
        assert "timestamp" in evt

    @pytest.mark.asyncio
    async def test_namespace_and_tags_optional(self):
        """Backward compat: older callers without namespace/tags still work."""
        captured: list[str] = []

        class _FakeRedis:
            async def publish(self, channel: str, payload: str):
                captured.append(payload)

        with patch("app.events.publisher.get_redis", new=AsyncMock(return_value=_FakeRedis())):
            await publish_entity_event("created", "x", "chain")

        import json
        evt = json.loads(captured[0])
        # Defaults: namespace=None, tags=[].
        assert evt["namespace"] is None
        assert evt["tags"] == []
