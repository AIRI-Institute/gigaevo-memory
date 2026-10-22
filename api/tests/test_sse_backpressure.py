"""Tests for SSE backpressure (P2 §6): lag_warning + slow-consumer drop."""

from datetime import datetime, timedelta, timezone

import pytest

from app.routers.events import _compute_lag_action


NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)


def _event(*, lag_seconds: float | None) -> dict:
    """Build an event whose timestamp is ``lag_seconds`` behind NOW.

    ``lag_seconds=None`` produces an event without a timestamp field.
    """
    if lag_seconds is None:
        return {"event_type": "run_recorded", "entity_id": "x", "entity_type": "agent"}
    ts = (NOW - timedelta(seconds=lag_seconds)).isoformat()
    return {
        "event_type": "run_recorded",
        "entity_id": "x",
        "entity_type": "agent",
        "timestamp": ts,
    }


class TestComputeLagAction:
    """Pure decision logic — no I/O, no SSE round-trip."""

    def test_forward_when_within_budget(self):
        action, lag = _compute_lag_action(
            _event(lag_seconds=2.0),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        assert action == "forward"
        assert 1.9 < lag < 2.1

    def test_warn_at_threshold(self):
        action, lag = _compute_lag_action(
            _event(lag_seconds=15.0),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        assert action == "warn"
        assert 14.9 < lag < 15.1

    def test_warn_at_exact_warn_boundary(self):
        action, _lag = _compute_lag_action(
            _event(lag_seconds=10.0),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        # Boundary is inclusive on the warn side (>=).
        assert action == "warn"

    def test_drop_at_threshold(self):
        action, lag = _compute_lag_action(
            _event(lag_seconds=90.0),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        assert action == "drop"
        assert 89.9 < lag < 90.1

    def test_drop_at_exact_drop_boundary(self):
        action, _ = _compute_lag_action(
            _event(lag_seconds=60.0),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        assert action == "drop"

    def test_negative_lag_treated_as_forward(self):
        """Clock skew or events from the future — don't penalise."""
        action, lag = _compute_lag_action(
            _event(lag_seconds=-5.0),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        assert action == "forward"
        assert lag < 0

    def test_missing_timestamp_is_forward(self):
        action, lag = _compute_lag_action(
            _event(lag_seconds=None),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        assert action == "forward"
        assert lag is None

    def test_unparsable_timestamp_is_forward(self):
        evt = _event(lag_seconds=5.0)
        evt["timestamp"] = "not-a-timestamp"
        action, lag = _compute_lag_action(
            evt, now=NOW, warn_threshold_s=10.0, drop_threshold_s=60.0
        )
        assert action == "forward"
        assert lag is None

    def test_naive_timestamp_assumed_utc(self):
        """Publisher emits tz-aware, but tolerate naive ISO strings too."""
        naive = (NOW - timedelta(seconds=15.0)).replace(tzinfo=None).isoformat()
        evt = {"event_type": "x", "timestamp": naive}
        action, _ = _compute_lag_action(
            evt, now=NOW, warn_threshold_s=10.0, drop_threshold_s=60.0
        )
        assert action == "warn"


class TestThresholdConfiguration:
    """The helper reads thresholds from ``settings`` when args omitted."""

    def test_thresholds_default_from_settings(self, monkeypatch):
        from app.routers import events as events_mod

        monkeypatch.setattr(events_mod.settings, "sse_warn_lag_seconds", 5.0)
        monkeypatch.setattr(events_mod.settings, "sse_drop_lag_seconds", 20.0)

        # 7s lag: above settings.warn (5), below settings.drop (20) → warn.
        action, _ = _compute_lag_action(_event(lag_seconds=7.0), now=NOW)
        assert action == "warn"

        # 25s lag: above settings.drop (20) → drop.
        action, _ = _compute_lag_action(_event(lag_seconds=25.0), now=NOW)
        assert action == "drop"

    def test_explicit_thresholds_override_settings(self, monkeypatch):
        from app.routers import events as events_mod

        monkeypatch.setattr(events_mod.settings, "sse_warn_lag_seconds", 100.0)
        monkeypatch.setattr(events_mod.settings, "sse_drop_lag_seconds", 200.0)

        # Explicit small thresholds beat the (huge) settings.
        action, _ = _compute_lag_action(
            _event(lag_seconds=11.0),
            now=NOW,
            warn_threshold_s=10.0,
            drop_threshold_s=60.0,
        )
        assert action == "warn"


class TestPublisherEventShapeIntegration:
    """Verify the helper handles the exact shape `publish_entity_event`
    emits (iter #17 enriched payload). This guards against drift
    between the publisher's timestamp format and the lag check."""

    @pytest.mark.asyncio
    async def test_publisher_payload_decodes_for_lag(self, monkeypatch):
        import json
        from unittest.mock import AsyncMock, patch

        from app.events.publisher import publish_entity_event

        captured: list[str] = []

        class _FakeRedis:
            async def publish(self, channel, payload):
                captured.append(payload)

        with patch("app.events.publisher.get_redis",
                   new=AsyncMock(return_value=_FakeRedis())):
            await publish_entity_event(
                "run_recorded", "ag-1", "agent",
                namespace="glazkov", tags=["finance"],
            )

        # Roundtrip the wire payload through the lag check.
        published_payload = json.loads(captured[0])
        # Use `now=` equal to the published timestamp so lag = 0.
        published_at = datetime.fromisoformat(published_payload["timestamp"])
        action, lag = _compute_lag_action(
            published_payload, now=published_at,
            warn_threshold_s=10.0, drop_threshold_s=60.0,
        )
        assert action == "forward"
        assert lag == pytest.approx(0.0, abs=1e-6)
