"""PlatformClient — thin HTTP wrapper around gigaevo-platform's API
(P1 §2.2, iter #43).

This client lives in the same Python distribution as
:class:`GigaEvoClient` so a single ``pip install gigaevo-client``
gives callers both surfaces. The backends are separate processes —
:class:`PlatformClient` points at a different ``base_url`` than the
Memory client and never shares an ``httpx.Client``.

Surface deliberately stays small in this iteration: the methods
match the §2.2 P1 spec one-for-one and return parsed JSON
dictionaries. Typed Pydantic models for ``ExperimentRef`` /
``EvolutionRef`` / ``Event`` can layer on later without breaking
this signature — callers that want strong typing today can pass
the returned dicts into their own models.

The async SSE streaming method (:meth:`stream_events`) is
sketched as a synchronous shape returning a generator of dicts
rather than the ``AsyncIterator[Event]`` the TODO specs, matching
how the Memory client's :meth:`watch_entities` is wired today.
"""

from __future__ import annotations

from typing import Any, Iterator

import httpx


class PlatformClient:
    """Client for the gigaevo-platform backend.

    Construct via ``PlatformClient(base_url=..., api_key=...)`` or
    via :meth:`from_config`, which pulls ``platform_base_url`` and
    ``api_key`` out of a :class:`GigaEvoConfig`.

    Every method makes a single HTTP round-trip and returns the
    parsed JSON response (typically a ``dict``). Failures raise the
    underlying ``httpx.HTTPStatusError`` so callers can inspect
    ``exc.response.status_code`` / ``exc.response.json()``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        timeout: float = 30.0,
        api_key: str | None = None,
    ):
        """Initialise the platform client.

        Args:
            base_url: Base URL of the gigaevo-platform server. Defaults
                to ``http://localhost:8001`` (the conventional sibling
                port to Memory's ``8000``).
            timeout: HTTP request timeout in seconds.
            api_key: Optional API key sent on every request as the
                ``X-API-Key`` header. Mirrors Memory's auth scheme so
                operators can issue a single key for both backends.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        headers = {"X-API-Key": api_key} if api_key else None
        self._http = httpx.Client(
            base_url=self._base_url, timeout=timeout, headers=headers
        )

    @classmethod
    def from_config(cls, config) -> "PlatformClient":
        """Construct from a :class:`GigaEvoConfig`. Uses
        ``platform_base_url`` (or falls back to the default
        ``http://localhost:8001`` when the config field is None)."""
        return cls(
            base_url=config.platform_base_url or "http://localhost:8001",
            timeout=config.timeout,
            api_key=config.api_key,
        )

    # -----------------------------------------------------------------
    # Read-only health + experiment listing
    # -----------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Wrap ``GET /api/v1/status``. Returns the platform health
        document (process counts, queue depths, last-heartbeat
        timestamps — shape defined by gigaevo-platform)."""
        return self._get("/api/v1/status")

    def list_experiments(self) -> list[dict[str, Any]]:
        """Wrap ``GET /api/v1/experiments``. Returns one summary
        dict per experiment."""
        return self._get("/api/v1/experiments")

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Wrap ``GET /api/v1/experiments/{id}``."""
        return self._get(f"/api/v1/experiments/{experiment_id}")

    def get_status(self, experiment_id: str) -> dict[str, Any]:
        """Wrap ``GET /api/v1/experiments/{id}/status``. Lightweight
        endpoint suitable for polling."""
        return self._get(f"/api/v1/experiments/{experiment_id}/status")

    def get_results(self, experiment_id: str) -> dict[str, Any]:
        """Wrap ``GET /api/v1/experiments/{id}/results``."""
        return self._get(f"/api/v1/experiments/{experiment_id}/results")

    # -----------------------------------------------------------------
    # Lifecycle mutators
    # -----------------------------------------------------------------

    def start_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Wrap ``POST /api/v1/experiments/{id}/start``."""
        return self._post(f"/api/v1/experiments/{experiment_id}/start")

    def stop_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Wrap ``POST /api/v1/experiments/{id}/stop``."""
        return self._post(f"/api/v1/experiments/{experiment_id}/stop")

    # -----------------------------------------------------------------
    # Creation
    # -----------------------------------------------------------------

    def create_chain_experiment(
        self, spec: dict[str, Any]
    ) -> dict[str, Any]:
        """Wrap ``POST /api/v1/experiments/chains``. ``spec`` is
        forwarded as the request JSON body; the server returns an
        experiment reference (typically ``{"experiment_id": ...,
        "status": "queued"}``)."""
        return self._post("/api/v1/experiments/chains", json=spec)

    def create_evolution(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Wrap ``POST /api/v1/evolutions``. Same shape as
        :meth:`create_chain_experiment` but pointed at the
        evolution-specific endpoint requested in Platform TODO §1."""
        return self._post("/api/v1/evolutions", json=spec)

    # -----------------------------------------------------------------
    # Evolution inspection (CARE PREPARE §2.6, Platform §4.2 / §4.4)
    # -----------------------------------------------------------------

    def get_evolution(self, evolution_id: str) -> dict[str, Any]:
        """Wrap ``GET /api/v1/evolutions/{id}``.

        Returns the current evolution state: generation counter,
        best-of-generation history, Pareto front, status (`queued` /
        `running` / `completed` / `failed` / `cancelled`).
        """
        return self._get(f"/api/v1/evolutions/{evolution_id}")

    def list_individuals(
        self, evolution_id: str
    ) -> list[dict[str, Any]]:
        """Wrap ``GET /api/v1/evolutions/{id}/individuals``.

        Returns one dict per individual in the population, with
        fitness scores + lineage metadata. Order is server-defined
        (Pareto-rank-then-crowding for multi-objective; descending
        fitness for single-objective).
        """
        return self._get(f"/api/v1/evolutions/{evolution_id}/individuals")

    def accept_individual(
        self,
        evolution_id: str,
        individual_id: str,
    ) -> dict[str, Any]:
        """Wrap ``POST /api/v1/evolutions/{id}/accept``.

        Promotes ``individual_id`` to Memory's ``stable`` channel.
        Idempotent on the same ``individual_id``: calling twice with
        the same id returns the same response. Switching to a
        different id after a prior accept yields ``409 Conflict``;
        callers should inspect ``exc.response.json()`` for the
        currently-accepted id.
        """
        return self._post(
            f"/api/v1/evolutions/{evolution_id}/accept",
            json={"individual_id": individual_id},
        )

    # -----------------------------------------------------------------
    # Event stream
    # -----------------------------------------------------------------

    def stream_events(self, experiment_id: str) -> Iterator[dict[str, Any]]:
        """Stream SSE events for ``experiment_id``.

        Yields parsed ``dict``s for each ``data:`` frame. The
        connection stays open until the server closes it or the
        consumer breaks out of the loop.

        The TODO sketched this as ``AsyncIterator[Event]``; the
        synchronous generator here matches Memory's
        :meth:`watch_entities` shape today. Async support layers in
        when the gigaevo-platform SSE endpoint stabilises.
        """
        import json

        url = f"/api/v1/experiments/{experiment_id}/events"
        with self._http.stream("GET", url) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                # SSE: lines prefixed with "data: ".
                if line.startswith("data: "):
                    payload = line[len("data: "):]
                    if payload.strip():
                        yield json.loads(payload)

    # -----------------------------------------------------------------
    # HTTP helpers + lifecycle
    # -----------------------------------------------------------------

    def _get(self, path: str) -> Any:
        resp = self._http.get(path)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict | None = None) -> Any:
        resp = self._http.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        """Release the underlying httpx connection pool."""
        self._http.close()

    def __enter__(self) -> "PlatformClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
