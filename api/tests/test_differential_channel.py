"""Tests for the differential channel view endpoint (TODO §5 P3).

Three layers:
  1. Pure helper ``EntityService._extract_objective_value`` — branches
     for ``fitness_score`` (with legacy fallback) vs. arbitrary objective
     names + unparsable values.
  2. ``EntityService.find_versions_beating`` end-to-end against a
     stubbed DB session — covers strict-``>`` filtering, sort direction,
     limit cap, baseline edge cases.
  3. ``GET /v1/chains/{id}/versions/beating`` HTTP path — happy path
     with the service stubbed, 404 on missing chain, 404 when entity
     is wrong type, "no baseline" structured-empty response, OpenAPI
     surface.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.services.entity_service import EntityService


# ---------------------------------------------------------------------------
# Pure helper: _extract_objective_value
# ---------------------------------------------------------------------------


class TestExtractObjectiveValue:
    def test_fitness_score_wins_over_legacy_fitness(self):
        meta = {"fitness_score": 0.9, "fitness": 0.1}
        assert EntityService._extract_objective_value(meta, "fitness_score") == 0.9

    def test_legacy_fitness_fallback(self):
        meta = {"fitness": 0.7}
        assert EntityService._extract_objective_value(meta, "fitness_score") == 0.7

    def test_named_objective_from_objectives_dict(self):
        meta = {"objectives": {"accuracy": 0.92, "latency_ms": 130}}
        assert EntityService._extract_objective_value(meta, "accuracy") == 0.92
        assert EntityService._extract_objective_value(meta, "latency_ms") == 130.0

    def test_missing_named_objective_returns_none(self):
        meta = {"objectives": {"accuracy": 0.5}}
        assert EntityService._extract_objective_value(meta, "tokens") is None

    def test_objectives_not_a_dict_returns_none(self):
        # Defensive: a pre-2026 row may have an unexpected shape.
        assert EntityService._extract_objective_value({"objectives": "weird"}, "accuracy") is None

    def test_none_meta(self):
        assert EntityService._extract_objective_value(None, "fitness_score") is None

    def test_unparsable_value_returns_none(self):
        meta = {"fitness_score": "not-a-number"}
        assert EntityService._extract_objective_value(meta, "fitness_score") is None

    def test_int_coerced_to_float(self):
        meta = {"fitness_score": 1}
        assert EntityService._extract_objective_value(meta, "fitness_score") == 1.0


# ---------------------------------------------------------------------------
# Service: find_versions_beating
# ---------------------------------------------------------------------------


def _ts(offset_min: int) -> datetime:
    base = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
    return base - timedelta(minutes=offset_min)


def _fake_version(version_id, *, number, fitness_score=None, objectives=None,
                  author="mage", change_summary=None, offset_min=0):
    v = MagicMock()
    v.version_id = uuid.UUID(version_id)
    v.entity_id = uuid.uuid4()  # service filters by entity_id in the stmt
    v.version_number = number
    em: dict = {}
    if fitness_score is not None:
        em["fitness_score"] = fitness_score
    if objectives is not None:
        em["objectives"] = objectives
    v.evolution_meta = em or None
    v.author = author
    v.change_summary = change_summary
    v.created_at = _ts(offset_min)
    return v


def _build_service(*, entity, baseline_version, all_versions):
    """Hand-stub the service's `db.execute` so the method's three reads
    (entity / baseline_version / all_versions) return the right things."""
    svc = EntityService(MagicMock())

    async def fake_execute(stmt):
        # Inspect the SQL roughly to decide which read is happening.
        s = str(stmt)
        result = MagicMock()
        if "FROM entity_versions" in s and "WHERE entity_versions.entity_id" in s:
            result.scalars.return_value.all.return_value = all_versions
        elif "FROM entities" in s:
            result.scalar_one_or_none.return_value = entity
        else:
            # version_id lookup
            result.scalar_one_or_none.return_value = baseline_version
        return result

    svc.db.execute = fake_execute  # type: ignore[assignment]
    return svc


class TestFindVersionsBeating:
    BASELINE_VID = "11111111-2222-3333-4444-555555555555"
    BASELINE_EID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    def _entity(self, **channel_overrides):
        e = MagicMock()
        e.entity_id = uuid.UUID(self.BASELINE_EID)
        e.deleted_at = None
        e.entity_type = "chain"
        channels = {"stable": self.BASELINE_VID, "latest": self.BASELINE_VID}
        channels.update(channel_overrides)
        e.channels = channels
        return e

    def test_missing_entity_returns_none(self):
        svc = _build_service(entity=None, baseline_version=None, all_versions=[])
        result = asyncio.run(svc.find_versions_beating(uuid.UUID(self.BASELINE_EID)))
        assert result is None

    def test_strict_greater_filter(self):
        baseline = _fake_version(self.BASELINE_VID, number=3, fitness_score=0.61)
        # 5 versions including the baseline. Two beat it, one ties (excluded),
        # one is lower, one has no fitness recorded.
        versions = [
            _fake_version("00000000-0000-0000-0000-000000000001", number=1, fitness_score=0.30),
            _fake_version("00000000-0000-0000-0000-000000000002", number=2, fitness_score=0.61),  # tie → excluded
            baseline,  # baseline itself → excluded
            _fake_version("00000000-0000-0000-0000-000000000004", number=4, fitness_score=0.83),
            _fake_version("00000000-0000-0000-0000-000000000005", number=5, fitness_score=0.72),
            _fake_version("00000000-0000-0000-0000-000000000006", number=6),  # no fitness
        ]
        svc = _build_service(
            entity=self._entity(), baseline_version=baseline, all_versions=versions
        )
        result = asyncio.run(svc.find_versions_beating(uuid.UUID(self.BASELINE_EID)))
        assert result is not None
        # baseline_value reported.
        assert result["baseline_value"] == 0.61
        # Two winners: 0.83 and 0.72. Default sort desc.
        values = [w["value"] for w in result["winners"]]
        assert values == [0.83, 0.72]
        # Deltas positive.
        deltas = [round(w["delta"], 4) for w in result["winners"]]
        assert deltas == [round(0.83 - 0.61, 4), round(0.72 - 0.61, 4)]

    def test_sort_dir_asc(self):
        baseline = _fake_version(self.BASELINE_VID, number=3, fitness_score=0.50)
        versions = [
            baseline,
            _fake_version("00000000-0000-0000-0000-000000000010", number=10, fitness_score=0.92),
            _fake_version("00000000-0000-0000-0000-000000000011", number=11, fitness_score=0.66),
        ]
        svc = _build_service(
            entity=self._entity(), baseline_version=baseline, all_versions=versions
        )
        result = asyncio.run(svc.find_versions_beating(
            uuid.UUID(self.BASELINE_EID), sort_dir="asc",
        ))
        assert result is not None
        values = [w["value"] for w in result["winners"]]
        assert values == [0.66, 0.92]

    def test_limit_cap(self):
        baseline = _fake_version(self.BASELINE_VID, number=1, fitness_score=0.10)
        # 5 winners — cap at 3.
        versions = [baseline] + [
            _fake_version(
                f"00000000-0000-0000-0000-00000000200{i}",
                number=10 + i,
                fitness_score=0.20 + 0.1 * i,
            )
            for i in range(5)
        ]
        svc = _build_service(
            entity=self._entity(), baseline_version=baseline, all_versions=versions
        )
        result = asyncio.run(svc.find_versions_beating(
            uuid.UUID(self.BASELINE_EID), limit=3,
        ))
        assert result is not None
        assert len(result["winners"]) == 3
        # Top 3 highest values (default desc).
        values = [w["value"] for w in result["winners"]]
        # 0.20, 0.30, 0.40, 0.50, 0.60 → top 3 = 0.60, 0.50, 0.40
        assert values == pytest.approx([0.60, 0.50, 0.40], abs=1e-9)

    def test_named_objective(self):
        baseline = _fake_version(
            self.BASELINE_VID, number=1, objectives={"accuracy": 0.80, "latency_ms": 200},
        )
        versions = [
            baseline,
            _fake_version(
                "00000000-0000-0000-0000-000000000a01", number=2,
                objectives={"accuracy": 0.85, "latency_ms": 220},
            ),
            _fake_version(
                "00000000-0000-0000-0000-000000000a02", number=3,
                objectives={"accuracy": 0.75},  # lower → excluded
            ),
        ]
        svc = _build_service(
            entity=self._entity(), baseline_version=baseline, all_versions=versions,
        )
        result = asyncio.run(svc.find_versions_beating(
            uuid.UUID(self.BASELINE_EID), objective="accuracy",
        ))
        assert result is not None
        assert result["baseline_value"] == 0.80
        assert [w["value"] for w in result["winners"]] == [0.85]

    def test_no_baseline_pin_returns_structured_empty(self):
        # Channel doesn't exist → baseline_version is None.
        entity = self._entity()
        entity.channels = {"latest": self.BASELINE_VID}  # no `stable`
        svc = _build_service(
            entity=entity,
            baseline_version=None,
            all_versions=[
                _fake_version("00000000-0000-0000-0000-000000000077", number=1, fitness_score=0.9),
            ],
        )
        result = asyncio.run(svc.find_versions_beating(uuid.UUID(self.BASELINE_EID)))
        assert result is not None
        assert result["baseline_value"] is None
        assert result["winners"] == []
        assert result["baseline_version_id"] is None

    def test_baseline_pinned_but_no_fitness(self):
        baseline = _fake_version(self.BASELINE_VID, number=1)  # no fitness
        svc = _build_service(
            entity=self._entity(),
            baseline_version=baseline,
            all_versions=[
                _fake_version("00000000-0000-0000-0000-000000000088", number=2, fitness_score=0.9),
            ],
        )
        result = asyncio.run(svc.find_versions_beating(uuid.UUID(self.BASELINE_EID)))
        assert result is not None
        assert result["baseline_value"] is None
        assert result["winners"] == []
        # baseline_version_id surfaces — only the value is missing.
        assert result["baseline_version_id"] == self.BASELINE_VID


# ---------------------------------------------------------------------------
# Endpoint: GET /v1/chains/{id}/versions/beating
# ---------------------------------------------------------------------------


@pytest.fixture
def http_client():
    async def _get_db():
        yield MagicMock()
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _stub_find(monkeypatch, *, return_value):
    async def fake(self, entity_id, **kwargs):
        return return_value
    monkeypatch.setattr(EntityService, "find_versions_beating", fake)


def _stub_get_entity(monkeypatch, *, entity_type="chain"):
    async def fake(self, entity_id, channel="latest"):
        entity = MagicMock()
        entity.entity_type = entity_type
        return entity, MagicMock()
    monkeypatch.setattr(EntityService, "get_entity", fake)


class TestEndpoint:
    def test_happy_path_returns_winners(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value={
            "entity_id": "e-1",
            "baseline_channel": "stable",
            "baseline_version_id": "v-stable",
            "objective": "fitness_score",
            "baseline_value": 0.6,
            "winners": [
                {
                    "version_id": "v-2",
                    "version_number": 5,
                    "value": 0.85,
                    "delta": 0.25,
                    "author": "mage",
                    "created_at": "2026-05-16T11:00:00+00:00",
                    "change_summary": None,
                },
            ],
        })
        _stub_get_entity(monkeypatch)

        eid = uuid.uuid4()
        r = http_client.get(f"/v1/chains/{eid}/versions/beating")
        assert r.status_code == 200
        body = r.json()
        assert body["objective"] == "fitness_score"
        assert body["baseline_value"] == 0.6
        assert len(body["winners"]) == 1
        assert body["winners"][0]["delta"] == 0.25

    def test_query_params_threaded_through(self, http_client, monkeypatch):
        captured: dict = {}

        async def fake(self, entity_id, *, baseline_channel, objective, limit, sort_dir):
            captured["baseline_channel"] = baseline_channel
            captured["objective"] = objective
            captured["limit"] = limit
            captured["sort_dir"] = sort_dir
            return {
                "entity_id": str(entity_id),
                "baseline_channel": baseline_channel,
                "baseline_version_id": None,
                "objective": objective,
                "baseline_value": None,
                "winners": [],
            }
        monkeypatch.setattr(EntityService, "find_versions_beating", fake)
        _stub_get_entity(monkeypatch)

        eid = uuid.uuid4()
        r = http_client.get(
            f"/v1/chains/{eid}/versions/beating",
            params={"channel": "evolved", "objective": "accuracy",
                    "limit": 25, "sort_dir": "asc"},
        )
        assert r.status_code == 200
        assert captured == {
            "baseline_channel": "evolved",
            "objective": "accuracy",
            "limit": 25,
            "sort_dir": "asc",
        }

    def test_chain_not_found_returns_404(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value=None)
        eid = uuid.uuid4()
        r = http_client.get(f"/v1/chains/{eid}/versions/beating")
        assert r.status_code == 404

    def test_wrong_entity_type_returns_404(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value={
            "entity_id": "e-1",
            "baseline_channel": "stable",
            "baseline_version_id": None,
            "objective": "fitness_score",
            "baseline_value": None,
            "winners": [],
        })
        # Entity exists but is, say, an agent.
        _stub_get_entity(monkeypatch, entity_type="agent")

        eid = uuid.uuid4()
        r = http_client.get(f"/v1/chains/{eid}/versions/beating")
        assert r.status_code == 404

    def test_no_baseline_renders_structured_empty(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value={
            "entity_id": "e-1",
            "baseline_channel": "stable",
            "baseline_version_id": None,
            "objective": "fitness_score",
            "baseline_value": None,
            "winners": [],
        })
        _stub_get_entity(monkeypatch)

        eid = uuid.uuid4()
        r = http_client.get(f"/v1/chains/{eid}/versions/beating")
        assert r.status_code == 200
        body = r.json()
        assert body["baseline_value"] is None
        assert body["winners"] == []

    def test_invalid_sort_dir_rejected(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value=None)
        _stub_get_entity(monkeypatch)
        eid = uuid.uuid4()
        r = http_client.get(
            f"/v1/chains/{eid}/versions/beating",
            params={"sort_dir": "random"},
        )
        assert r.status_code == 422

    def test_limit_bounds_enforced(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value=None)
        eid = uuid.uuid4()
        r = http_client.get(
            f"/v1/chains/{eid}/versions/beating", params={"limit": 0},
        )
        assert r.status_code == 422
        r = http_client.get(
            f"/v1/chains/{eid}/versions/beating", params={"limit": 9999},
        )
        assert r.status_code == 422

    def test_endpoint_registered_in_openapi(self):
        schema = app.openapi()
        assert "/v1/chains/{chain_id}/versions/beating" in schema["paths"]
        # Confirm the response component is wired up.
        assert "DifferentialChannelView" in schema["components"]["schemas"]
        assert "VersionScore" in schema["components"]["schemas"]
