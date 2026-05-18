"""SSE-based subscription for entity change notifications."""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

import httpx
from httpx_sse import connect_sse

from ._compat import chain_from_content

if TYPE_CHECKING:
    from .client import MemoryClient


class Subscription:
    """Background SSE subscription that calls a callback on entity changes.

    Usage::

        def on_update(new_chain: ReasoningChain):
            agent.chain = new_chain

        sub = client.watch_chain(entity_id, callback=on_update)
        # ... later ...
        sub.stop()
    """

    def __init__(
        self,
        client: MemoryClient,
        entity_id: str | None = None,
        entity_type: str | None = None,
        callback: Callable[[Any], None] | None = None,
        *,
        namespace: str | None = None,
        tags: list[str] | None = None,
        event_type: str | None = None,
    ):
        self._client = client
        self._entity_id = entity_id
        self._entity_type = entity_type
        self._callback = callback
        self._namespace = namespace
        self._tags = list(tags) if tags else None
        self._event_type = event_type
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start listening in a background daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop listening and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _listen(self) -> None:
        base_url = self._client._base_url
        params: dict[str, Any] = {}
        if self._entity_type is not None:
            params["entity_type"] = self._entity_type
        if self._entity_id is not None:
            params["entity_id"] = self._entity_id
        if self._namespace is not None:
            params["namespace"] = self._namespace
        if self._event_type is not None:
            params["event_type"] = self._event_type
        if self._tags:
            params["tags"] = list(self._tags)

        while not self._stop_event.is_set():
            try:
                with httpx.Client(base_url=base_url, timeout=None) as http:
                    with connect_sse(
                        http, "GET", "/v1/events/stream", params=params
                    ) as sse:
                        for event in sse.iter_sse():
                            if self._stop_event.is_set():
                                break
                            if event.event == "entity_changed":
                                self._handle_event(event.data)
            except Exception:
                # Reconnect after delay on any failure
                if not self._stop_event.is_set():
                    time.sleep(5)

    def _handle_event(self, raw_data: str) -> None:
        """Process a single SSE event."""
        try:
            data = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            return

        if self._callback is None:
            return

        try:
            # Auto-refresh + ReasoningChain coercion only when the
            # subscription is pinned to a single chain. Generic / multi-
            # entity subscriptions (e.g. `watch_entities(namespace=...)`)
            # pass the raw event dict to the callback — refreshing every
            # match would explode the server load.
            if self._entity_type == "chain" and self._entity_id is not None:
                new_content = self._client.get_chain_dict(
                    self._entity_id, force_refresh=True
                )
                new_obj: Any = chain_from_content(new_content)
            else:
                new_obj = data
            self._callback(new_obj)
        except Exception:
            pass  # Don't crash the listener on callback errors
