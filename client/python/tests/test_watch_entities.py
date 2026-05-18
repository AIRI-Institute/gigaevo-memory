"""Tests for ``MemoryClient.watch_entities`` and the extended
``Subscription`` class supporting namespace/tags/event_type filters."""

import pytest

from gigaevo_memory import MemoryClient
from gigaevo_memory.watcher import Subscription


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


class TestSubscriptionParamShape:
    """Verify the params the Subscription will send to /v1/events/stream."""

    def _build_params(self, sub: Subscription) -> dict:
        """Replicate the dict build inside `_listen` so we can inspect it
        without actually opening an SSE connection."""
        params: dict = {}
        if sub._entity_type is not None:
            params["entity_type"] = sub._entity_type
        if sub._entity_id is not None:
            params["entity_id"] = sub._entity_id
        if sub._namespace is not None:
            params["namespace"] = sub._namespace
        if sub._event_type is not None:
            params["event_type"] = sub._event_type
        if sub._tags:
            params["tags"] = list(sub._tags)
        return params

    def test_no_filters_means_no_params(self, client):
        sub = Subscription(client, callback=lambda _e: None)
        assert self._build_params(sub) == {}

    def test_chain_pinned_subscription(self, client):
        sub = Subscription(
            client, entity_id="ch-001", entity_type="chain", callback=lambda _: None
        )
        assert self._build_params(sub) == {
            "entity_type": "chain",
            "entity_id": "ch-001",
        }

    def test_namespace_only(self, client):
        sub = Subscription(
            client, callback=lambda _: None, namespace="glazkov"
        )
        assert self._build_params(sub) == {"namespace": "glazkov"}

    def test_all_filters_combined(self, client):
        sub = Subscription(
            client,
            entity_type="agent",
            callback=lambda _: None,
            namespace="glazkov",
            tags=["finance", "monthly"],
            event_type="run_recorded",
        )
        params = self._build_params(sub)
        assert params == {
            "entity_type": "agent",
            "namespace": "glazkov",
            "tags": ["finance", "monthly"],
            "event_type": "run_recorded",
        }


class TestEventHandling:
    """Verify event dispatch + callback isolation."""

    def test_callback_receives_raw_event_for_generic_subscription(self, client):
        received: list[dict] = []

        sub = Subscription(
            client,
            callback=received.append,
            namespace="glazkov",  # not a chain pin — raw dict path
        )
        # Directly exercise _handle_event without spinning the thread.
        sub._handle_event(
            '{"event_type": "run_recorded", "entity_id": "ag-1", '
            '"entity_type": "agent", "namespace": "glazkov", "tags": ["f"]}'
        )
        assert len(received) == 1
        assert received[0]["event_type"] == "run_recorded"
        assert received[0]["namespace"] == "glazkov"

    def test_invalid_json_is_silently_dropped(self, client):
        received: list = []
        sub = Subscription(client, callback=received.append, namespace="x")
        sub._handle_event("not-json")
        assert received == []

    def test_callback_none_skipped_gracefully(self, client):
        """A Subscription built with no callback shouldn't crash on events."""
        sub = Subscription(client)  # no callback
        sub._handle_event('{"event_type": "x"}')  # must not raise

    def test_chain_pin_path_calls_get_chain_dict(self, client, monkeypatch):
        """When entity_type=='chain' AND entity_id set, the watcher refetches
        the chain and coerces via chain_from_content (legacy behaviour)."""
        seen: list = []

        def _fake_get_chain_dict(entity_id, force_refresh=False):
            seen.append((entity_id, force_refresh))
            return {"version": "1.1", "steps": []}

        from gigaevo_memory import watcher as _wm
        monkeypatch.setattr(_wm, "chain_from_content", lambda c: ("CHAIN", c))
        monkeypatch.setattr(client, "get_chain_dict", _fake_get_chain_dict)

        out: list = []
        sub = Subscription(
            client, entity_id="ch-1", entity_type="chain", callback=out.append
        )
        sub._handle_event('{"event_type": "updated", "entity_id": "ch-1"}')
        assert seen == [("ch-1", True)]
        assert out == [("CHAIN", {"version": "1.1", "steps": []})]


class TestWatchEntitiesPublicAPI:
    """`MemoryClient.watch_entities()` constructs a properly-filtered
    Subscription and starts it."""

    def test_returns_running_subscription(self, client, monkeypatch):
        # Stop _listen from actually connecting.
        from gigaevo_memory import watcher as _wm
        monkeypatch.setattr(_wm.Subscription, "_listen", lambda self: None)

        sub = client.watch_entities(
            lambda _e: None,
            entity_type="agent",
            namespace="glazkov",
            tags=["pdf"],
            event_type="run_recorded",
        )
        try:
            assert isinstance(sub, _wm.Subscription)
            # Filters propagated.
            assert sub._entity_type == "agent"
            assert sub._namespace == "glazkov"
            assert sub._tags == ["pdf"]
            assert sub._event_type == "run_recorded"
        finally:
            sub.stop()

    def test_watch_chain_still_works(self, client, monkeypatch):
        """Existing watch_chain API is unchanged."""
        from gigaevo_memory import watcher as _wm
        monkeypatch.setattr(_wm.Subscription, "_listen", lambda self: None)

        sub = client.watch_chain("ch-1", lambda _: None)
        try:
            assert sub._entity_type == "chain"
            assert sub._entity_id == "ch-1"
        finally:
            sub.stop()
