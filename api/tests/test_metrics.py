"""Tests for the Prometheus /metrics endpoint (TODO §7 P3).

Three layers:
  1. Pure-function checks on the metrics module (path-template
     resolution, registry shape, scrape-path skip).
  2. Middleware behaviour: requests increment the counter + histogram
     under the correct labels, with the FastAPI route template (not
     the raw path).
  3. Endpoint integration: ``GET /metrics`` returns the Prometheus
     exposition format, populates entity gauges from a stubbed DB,
     and never appears in its own counters.
"""

from __future__ import annotations

import re
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import metrics
from app.db.session import get_db
from app.main import app


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


class TestRegistryShape:
    EXPECTED_NAMES = {
        "gigaevo_memory_http_requests_total",
        "gigaevo_memory_http_request_duration_seconds",
        "gigaevo_memory_entities",
    }

    def test_three_series_registered(self):
        names = {
            family.name
            for family in metrics.REGISTRY.collect()
        }
        # Counter shows up as "<name>" (the _total suffix is stripped by
        # the family iterator); histogram bare name; gauge bare name.
        names_with_total = {
            n + "_total" if not n.endswith("_total") else n for n in names
        }
        for expected in self.EXPECTED_NAMES:
            base = expected.removesuffix("_total")
            assert (
                expected in names_with_total or base in names
            ), f"{expected} not in {names}"

    def test_histogram_has_tuned_buckets(self):
        # Buckets must cover 5ms → 10s for memory-API latency profile.
        # Read them off the spec rather than poking internals.
        from app.metrics import _DURATION_BUCKETS

        assert 0.005 in _DURATION_BUCKETS
        assert 10.0 in _DURATION_BUCKETS
        # Strictly increasing.
        assert list(_DURATION_BUCKETS) == sorted(_DURATION_BUCKETS)


# ---------------------------------------------------------------------------
# Path-template resolution
# ---------------------------------------------------------------------------


class TestPathTemplate:
    def test_unmatched_path_falls_back(self):
        req = MagicMock()
        req.scope = {}
        assert metrics._resolve_path_template(req) == "unmatched"

    def test_uses_route_path_when_present(self):
        req = MagicMock()
        route = MagicMock()
        route.path = "/v1/chains/{chain_id}"
        req.scope = {"route": route}
        assert metrics._resolve_path_template(req) == "/v1/chains/{chain_id}"

    def test_route_without_path_falls_back(self):
        req = MagicMock()
        route = MagicMock(spec=[])  # no .path attribute
        req.scope = {"route": route}
        assert metrics._resolve_path_template(req) == "unmatched"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_metrics():
    """Clear the in-process metric state between tests so counter
    assertions reflect only this test's traffic."""
    metrics.http_requests_total.clear()
    metrics.http_request_duration_seconds.clear()
    metrics.entities_gauge.clear()
    yield


@pytest.fixture
def client(monkeypatch):
    """TestClient with the DB dependency stubbed out. ``refresh_entity_counts``
    is also stubbed so /metrics doesn't actually hit Postgres."""

    async def _get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _get_db

    async def _noop_refresh():
        return None

    monkeypatch.setattr(metrics, "refresh_entity_counts", _noop_refresh)
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _counter_value(*, method: str, path_template: str, status: str) -> float:
    samples = list(metrics.http_requests_total.collect())[0].samples
    for s in samples:
        if (
            s.labels.get("method") == method
            and s.labels.get("path_template") == path_template
            and s.labels.get("status") == status
        ):
            return s.value
    return 0.0


def _histogram_sample_count(*, method: str, path_template: str) -> float:
    """Read the histogram's ``_count`` sample for a label set."""
    samples = list(metrics.http_request_duration_seconds.collect())[0].samples
    for s in samples:
        if (
            s.name.endswith("_count")
            and s.labels.get("method") == method
            and s.labels.get("path_template") == path_template
        ):
            return s.value
    return 0.0


# ---------------------------------------------------------------------------
# Middleware behaviour
# ---------------------------------------------------------------------------


class TestMiddleware:
    def test_request_increments_counter(self, client):
        r = client.get("/health")
        assert r.status_code in (200, 503)
        assert _counter_value(
            method="GET", path_template="/health", status=str(r.status_code)
        ) == 1.0

    def test_request_observes_duration(self, client):
        client.get("/health")
        # The histogram's _count must reflect one observation.
        assert _histogram_sample_count(
            method="GET", path_template="/health"
        ) == 1.0

    def test_uses_route_template_not_raw_path(self, client, monkeypatch):
        """Two requests to /v1/chains/<uuid>/... must collapse onto one
        label, not mint two separate label sets. Stubs the entity
        service so the handler short-circuits to 404 without
        attempting real DB I/O."""
        from app.services import entity_service

        async def fake_get_entity(self, entity_id, channel="latest"):
            return None

        monkeypatch.setattr(
            entity_service.EntityService, "get_entity", fake_get_entity
        )

        client.get(f"/v1/chains/{uuid.uuid4()}")
        client.get(f"/v1/chains/{uuid.uuid4()}")

        samples = list(metrics.http_requests_total.collect())[0].samples
        chain_templates = {
            s.labels["path_template"]
            for s in samples
            if "chains" in s.labels.get("path_template", "")
        }
        # Every chain-fetch must end up under the same template — never
        # the raw UUID path.
        assert chain_templates, [s.labels for s in samples]
        for t in chain_templates:
            assert "{" in t, t
            # Sanity: the raw UUID must not appear as a template label.
            assert not re.search(r"[0-9a-f]{8}-", t), t

    def test_status_label_reflects_response(self, client):
        # Hitting an unknown path → 404. Confirm the label says "404".
        client.get("/this-route-does-not-exist")
        # The path doesn't match any route, so falls back to "unmatched"
        # — but the status label must still be "404".
        assert _counter_value(
            method="GET", path_template="unmatched", status="404"
        ) == 1.0

    def test_metrics_scrape_path_not_self_counted(self, client):
        # /metrics request should NOT increment the counter — that
        # would create a self-referential spike on every scrape.
        client.get("/metrics")
        samples = list(metrics.http_requests_total.collect())[0].samples
        templates = {s.labels.get("path_template", "") for s in samples}
        assert "/metrics" not in templates, templates

    def test_method_label_recorded(self, client):
        client.get("/health")
        # POST to the same path would land on a different label set.
        assert _counter_value(
            method="GET", path_template="/health", status="200"
        ) >= 1.0


# ---------------------------------------------------------------------------
# Endpoint integration
# ---------------------------------------------------------------------------


class TestEndpoint:
    def test_returns_text_plain_with_prometheus_content_type(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        # Prometheus exposition uses a specific content type; the
        # exact suffix may vary by library version.
        assert "text/plain" in r.headers["content-type"]
        assert "version=" in r.headers["content-type"]

    def test_response_carries_metric_names(self, client):
        # Generate a request first so at least one counter sample exists.
        client.get("/health")
        r = client.get("/metrics")
        body = r.text
        assert "gigaevo_memory_http_requests_total" in body
        assert "gigaevo_memory_http_request_duration_seconds" in body
        # Gauge name surfaces in HELP / TYPE lines even when no samples
        # exist yet.
        assert "gigaevo_memory_entities" in body

    def test_help_and_type_lines_present(self, client):
        r = client.get("/metrics")
        # Standard exposition includes HELP and TYPE comments.
        assert re.search(r"# HELP gigaevo_memory_http_requests_total ", r.text)
        assert re.search(r"# TYPE gigaevo_memory_http_requests_total counter", r.text)

    def test_excluded_from_openapi_schema(self):
        # The /metrics path must not pollute the public OpenAPI doc —
        # Prometheus doesn't read OpenAPI, and the user-facing docs page
        # would surface a meaningless entry otherwise.
        schema = app.openapi()
        assert "/metrics" not in schema.get("paths", {})


# ---------------------------------------------------------------------------
# Entity-count refresh (DB-stubbed)
# ---------------------------------------------------------------------------


class TestEntityCountRefresh:
    def test_refresh_populates_gauge_from_db(self, monkeypatch):
        """Stub the session factory and verify the gauge labels match
        what the SQL returns."""

        class _Session:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def execute(self, stmt):
                result = MagicMock()
                result.all.return_value = [
                    ("chain", 12),
                    ("agent", 5),
                    ("memory_card", 3),
                ]
                return result

        def fake_factory():
            return _Session()

        monkeypatch.setattr(metrics, "async_session", fake_factory)

        import asyncio
        asyncio.run(metrics.refresh_entity_counts())

        samples = list(metrics.entities_gauge.collect())[0].samples
        by_type = {s.labels["entity_type"]: s.value for s in samples}
        assert by_type == {"chain": 12.0, "agent": 5.0, "memory_card": 3.0}

    def test_refresh_db_error_keeps_previous_values(self, monkeypatch):
        """A transient DB failure must not blow up the scrape — the
        gauge keeps its last good values so dashboards stay
        well-defined."""
        # Pre-seed the gauge with a known value.
        metrics.entities_gauge.labels(entity_type="chain").set(7.0)

        from sqlalchemy.exc import OperationalError

        class _ExplodingSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def execute(self, stmt):
                raise OperationalError("boom", {}, Exception("db down"))

        monkeypatch.setattr(metrics, "async_session", lambda: _ExplodingSession())

        import asyncio
        # Must not raise.
        asyncio.run(metrics.refresh_entity_counts())

        samples = list(metrics.entities_gauge.collect())[0].samples
        # The pre-seeded value must still be there.
        chain_samples = [s for s in samples if s.labels["entity_type"] == "chain"]
        assert chain_samples and chain_samples[0].value == 7.0
