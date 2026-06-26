"""Tests for the semantic deduplication endpoint (TODO §4 P3).

Three layers:
  1. Service: ``EntityService.find_duplicate_pairs`` — feature-flag
     gating, SQL parameter binding, canonical pair shape, namespace
     filter.
  2. Router: ``GET /v1/{entity_type}/duplicates`` — entity_type
     validation, 503 when vector search disabled, query params
     threaded through.
  3. OpenAPI: endpoint + response components registered.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.session import get_db
from app.main import app
from app.services.entity_service import EntityService


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_vector_flag():
    """Each test sets `enable_vector_search` to whatever it wants;
    restore the original value afterwards so the next test starts
    from the same baseline."""
    original = settings.enable_vector_search
    yield
    settings.enable_vector_search = original


def _mapping_rows(rows: list[dict]):
    """Build an execute() return value that mimics the
    `.mappings().all()` chain the service uses."""
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _make_service(*, rows: list[dict] | None = None):
    svc = EntityService(MagicMock())
    captured: dict = {}

    async def fake_execute(stmt, params=None):
        captured["sql"] = str(stmt)
        captured["params"] = params or {}
        return _mapping_rows(rows or [])

    svc.db.execute = fake_execute  # type: ignore[assignment]
    return svc, captured


class TestFindDuplicatePairs:
    def test_feature_flag_disabled_returns_none(self):
        settings.enable_vector_search = False
        svc, _ = _make_service()
        result = asyncio.run(svc.find_duplicate_pairs("chain"))
        assert result is None

    def test_feature_flag_enabled_runs_query(self):
        settings.enable_vector_search = True
        svc, captured = _make_service(rows=[])
        result = asyncio.run(svc.find_duplicate_pairs("chain"))
        assert result is not None
        # The SQL uses pgvector's cosine distance operator.
        assert "<=>" in captured["sql"]
        # Required filters: entity_type, deleted_at, embedding NOT NULL, channels has key.
        for needle in (
            "e.entity_type = :entity_type",
            "e.deleted_at IS NULL",
            "ev.embedding IS NOT NULL",
            "(e.channels ->> :channel) IS NOT NULL",
        ):
            assert needle in captured["sql"], needle
        # Canonical pair ordering (drops self + dedupes unordered pairs).
        assert "a.entity_id < b.entity_id" in captured["sql"]
        # Sort: similarity DESC.
        assert "ORDER BY similarity DESC" in captured["sql"]
        # Param binding.
        assert captured["params"]["entity_type"] == "chain"
        assert captured["params"]["channel"] == "latest"
        assert captured["params"]["threshold"] == 0.95

    def test_threshold_namespace_limit_passed(self):
        settings.enable_vector_search = True
        svc, captured = _make_service(rows=[])
        asyncio.run(svc.find_duplicate_pairs(
            "agent_skill",
            channel="stable",
            threshold=0.87,
            namespace="alice",
            limit=10,
        ))
        assert captured["params"] == {
            "entity_type": "agent_skill",
            "channel": "stable",
            "threshold": 0.87,
            "limit": 10,
            "namespace": "alice",
        }
        # Namespace filter is added to the SQL only when supplied.
        assert "e.namespace = :namespace" in captured["sql"]

    def test_namespace_omitted_drops_filter(self):
        settings.enable_vector_search = True
        svc, captured = _make_service(rows=[])
        asyncio.run(svc.find_duplicate_pairs("chain", namespace=None))
        assert "namespace" not in captured["params"]
        assert "e.namespace = :namespace" not in captured["sql"]

    def test_row_shape_translates_to_pairs(self):
        settings.enable_vector_search = True
        rows = [
            {
                "a_entity_id": "a-1", "a_version_id": "va-1",
                "a_name": "first-skill", "a_display_name": "First",
                "a_namespace": "alice",
                "b_entity_id": "b-2", "b_version_id": "vb-2",
                "b_name": "second-skill", "b_display_name": None,
                "b_namespace": "alice",
                "similarity": 0.987,
            },
        ]
        svc, _ = _make_service(rows=rows)
        result = asyncio.run(svc.find_duplicate_pairs("chain"))
        assert result is not None
        assert result == {
            "entity_type": "chain",
            "channel": "latest",
            "threshold": 0.95,
            "pairs": [{
                "entity_a": {
                    "entity_id": "a-1", "version_id": "va-1",
                    "name": "first-skill", "display_name": "First",
                    "namespace": "alice",
                },
                "entity_b": {
                    "entity_id": "b-2", "version_id": "vb-2",
                    "name": "second-skill", "display_name": None,
                    "namespace": "alice",
                },
                "similarity": 0.987,
                "suggestion": "merge",
            }],
        }

    def test_empty_rows_returns_empty_pairs(self):
        settings.enable_vector_search = True
        svc, _ = _make_service(rows=[])
        result = asyncio.run(svc.find_duplicate_pairs("agent"))
        assert result == {
            "entity_type": "agent", "channel": "latest",
            "threshold": 0.95, "pairs": [],
        }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@pytest.fixture
def http_client():
    async def _get_db():
        yield MagicMock()
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _stub_find(monkeypatch, *, return_value):
    captured: dict = {}

    async def fake(self, entity_type_singular, **kwargs):
        captured["entity_type_singular"] = entity_type_singular
        captured.update(kwargs)
        return return_value

    monkeypatch.setattr(EntityService, "find_duplicate_pairs", fake)
    return captured


class TestEndpoint:
    def test_happy_path(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value={
            "entity_type": "chain", "channel": "latest", "threshold": 0.95,
            "pairs": [
                {
                    "entity_a": {
                        "entity_id": "a", "version_id": "va",
                        "name": "n-a", "display_name": "A",
                        "namespace": None,
                    },
                    "entity_b": {
                        "entity_id": "b", "version_id": "vb",
                        "name": "n-b", "display_name": None,
                        "namespace": None,
                    },
                    "similarity": 0.99,
                    "suggestion": "merge",
                },
            ],
        })
        r = http_client.get("/v1/chains/duplicates")
        assert r.status_code == 200
        body = r.json()
        assert body["entity_type"] == "chain"
        assert body["threshold"] == 0.95
        assert len(body["pairs"]) == 1
        assert body["pairs"][0]["similarity"] == 0.99

    def test_503_when_vector_search_disabled(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value=None)
        r = http_client.get("/v1/chains/duplicates")
        assert r.status_code == 503
        assert "vector search" in r.json()["detail"].lower()

    def test_400_on_invalid_entity_type(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value=None)
        r = http_client.get("/v1/widgets/duplicates")
        assert r.status_code == 400
        assert "widgets" in r.json()["detail"]

    def test_hyphenated_entity_type_accepted(self, http_client, monkeypatch):
        captured = _stub_find(monkeypatch, return_value={
            "entity_type": "agent_skill", "channel": "latest",
            "threshold": 0.95, "pairs": [],
        })
        r = http_client.get("/v1/agent-skills/duplicates")
        assert r.status_code == 200
        # The router normalises hyphens → underscores before lookup.
        assert captured["entity_type_singular"] == "agent_skill"

    def test_query_params_threaded(self, http_client, monkeypatch):
        captured = _stub_find(monkeypatch, return_value={
            "entity_type": "chain", "channel": "stable",
            "threshold": 0.85, "pairs": [],
        })
        r = http_client.get(
            "/v1/chains/duplicates",
            params={
                "channel": "stable",
                "threshold": 0.85,
                "namespace": "alice",
                "limit": 25,
            },
        )
        assert r.status_code == 200
        assert captured["channel"] == "stable"
        assert captured["threshold"] == 0.85
        assert captured["namespace"] == "alice"
        assert captured["limit"] == 25

    def test_threshold_bounds_enforced(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value=None)
        r = http_client.get(
            "/v1/chains/duplicates", params={"threshold": 0.4},
        )
        assert r.status_code == 422
        r = http_client.get(
            "/v1/chains/duplicates", params={"threshold": 1.5},
        )
        assert r.status_code == 422

    def test_limit_bounds_enforced(self, http_client, monkeypatch):
        _stub_find(monkeypatch, return_value=None)
        r = http_client.get(
            "/v1/chains/duplicates", params={"limit": 0},
        )
        assert r.status_code == 422
        r = http_client.get(
            "/v1/chains/duplicates", params={"limit": 1000},
        )
        assert r.status_code == 422

    def test_endpoint_in_openapi(self):
        schema = app.openapi()
        # The path is /v1/{entity_type}/duplicates — appears under
        # whatever literal segment FastAPI uses for the template.
        paths = list(schema.get("paths", {}).keys())
        assert any("duplicates" in p for p in paths), paths
        assert "DuplicatesResponse" in schema["components"]["schemas"]
        assert "DuplicatePair" in schema["components"]["schemas"]
        assert "DuplicateMember" in schema["components"]["schemas"]
