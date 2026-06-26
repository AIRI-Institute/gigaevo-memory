"""Tests for the enriched `/health` payload (P2 §7).

CARE's TUI status bar polls /health; the response now carries enough
operational metrics (db pool stats, redis client counts, live entity
counts) to render the status line without extra round-trips.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    """Clear `app.dependency_overrides` between tests so a leaked
    override doesn't bleed into the next test."""
    yield
    app.dependency_overrides.clear()


def _stub_redis(connected: int = 3, blocked: int = 0) -> AsyncMock:
    r = AsyncMock()
    r.ping = AsyncMock()
    r.info = AsyncMock(
        return_value={"connected_clients": connected, "blocked_clients": blocked}
    )
    return r


def _stub_db(
    *,
    select_one_succeeds: bool = True,
    entity_count_rows: list[tuple[str, int]] | None = None,
) -> AsyncSession:
    """Build a mock session that:

    * answers ``SELECT 1`` with success/failure based on ``select_one_succeeds``;
    * answers the entity-count aggregation with ``entity_count_rows``.
    """
    db = AsyncMock(spec=AsyncSession)

    async def _execute(stmt):
        sql = str(stmt)
        if "SELECT 1" in sql:
            if not select_one_succeeds:
                raise RuntimeError("postgres down")
            return MagicMock()
        if "FROM entities" in sql:
            result = MagicMock()
            result.all = MagicMock(return_value=entity_count_rows or [])
            return result
        return MagicMock()

    db.execute = _execute
    return db


@pytest.fixture
def healthy_setup():
    """Wire FastAPI dependency_overrides + monkeypatch get_redis to
    return healthy stubs for the duration of a test."""
    db = _stub_db(
        entity_count_rows=[
            ("chain", 12), ("agent", 4), ("agent_skill", 8),
            ("memory_card", 23), ("step", 0),
        ]
    )

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    redis = _stub_redis(connected=3, blocked=0)
    with patch("app.routers.health.get_redis", new=AsyncMock(return_value=redis)):
        yield db, redis


class TestHealthEnrichedShape:
    def test_all_metrics_present_when_healthy(self, client, healthy_setup):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        # Status semantics preserved.
        assert body["status"] == "ok"
        assert body["postgres"] == "ok"
        assert body["redis"] == "ok"
        # New operational metrics.
        for k in (
            "db_pool_size",
            "db_pool_checkedin",
            "db_pool_checkedout",
            "db_pool_overflow",
            "redis_connected_clients",
            "redis_blocked_clients",
            "entity_counts",
            "entities",
            "auth",
        ):
            assert k in body, f"Missing /health field: {k}"
        assert body["auth"] in {"open", "required"}

    def test_entity_counts_aggregated_by_type(self, client, healthy_setup):
        body = client.get("/health").json()
        assert body["entity_counts"] == {
            "chain": 12,
            "agent": 4,
            "agent_skill": 8,
            "memory_card": 23,
            "step": 0,
        }
        assert body["entities"] == 47

    def test_redis_metrics_pulled_from_info(self, client, healthy_setup):
        body = client.get("/health").json()
        assert body["redis_connected_clients"] == 3
        assert body["redis_blocked_clients"] == 0

    def test_db_pool_stats_are_integers(self, client, healthy_setup):
        """SQLAlchemy returns ints; the JSON layer keeps them."""
        body = client.get("/health").json()
        for k in (
            "db_pool_size", "db_pool_checkedin",
            "db_pool_checkedout", "db_pool_overflow",
        ):
            # None or int — never a stringified float.
            assert body[k] is None or isinstance(body[k], int)


class TestGracefulDegradation:
    """A metric outage doesn't degrade the overall status; only failed
    dependency pings do."""

    def test_postgres_down_sets_degraded_and_skips_entity_counts(self, client):
        db = _stub_db(select_one_succeeds=False)

        async def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        with patch(
            "app.routers.health.get_redis",
            new=AsyncMock(return_value=_stub_redis()),
        ):
            body = client.get("/health").json()

        assert body["status"] == "degraded"
        assert body["postgres"].startswith("error:")
        # Entity counts skipped (would just error too) when postgres is down.
        assert body["entity_counts"] is None
        # Redis still healthy and surfaced.
        assert body["redis"] == "ok"
        assert body["redis_connected_clients"] == 3

    def test_redis_down_does_not_kill_metrics(self, client):
        """Redis ping fails; the metric fields collapse to None but
        the postgres half stays observable."""
        db = _stub_db(entity_count_rows=[("chain", 5)])

        async def _override_db():
            yield db

        broken_redis = AsyncMock()
        broken_redis.ping = AsyncMock(side_effect=RuntimeError("redis down"))
        broken_redis.info = AsyncMock(side_effect=RuntimeError("redis down"))

        app.dependency_overrides[get_db] = _override_db
        with patch(
            "app.routers.health.get_redis", new=AsyncMock(return_value=broken_redis)
        ):
            body = client.get("/health").json()

        assert body["status"] == "degraded"
        assert body["redis"].startswith("error:")
        # Metric fields collapse to None — not surfaced as "error: …" strings.
        assert body["redis_connected_clients"] is None
        assert body["redis_blocked_clients"] is None
        # Postgres half still works.
        assert body["postgres"] == "ok"
        assert body["entity_counts"] == {"chain": 5}

    def test_entity_count_query_failure_collapses_to_none(self, client):
        """If the entity-count aggregation throws (e.g. table missing
        in a partial migration), CARE's status bar shows ``—`` for
        counts without the overall status flipping."""
        broken_db = AsyncMock(spec=AsyncSession)

        async def _execute(stmt):
            sql = str(stmt)
            if "SELECT 1" in sql:
                return MagicMock()
            raise RuntimeError("entities table missing")

        broken_db.execute = _execute

        async def _override_db():
            yield broken_db

        app.dependency_overrides[get_db] = _override_db
        with patch(
            "app.routers.health.get_redis", new=AsyncMock(return_value=_stub_redis())
        ):
            body = client.get("/health").json()

        # Status stays ok — the SELECT 1 ping succeeded.
        assert body["status"] == "ok"
        assert body["postgres"] == "ok"
        # Counts gracefully degraded.
        assert body["entity_counts"] is None
