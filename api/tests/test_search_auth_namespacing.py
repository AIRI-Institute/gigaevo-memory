"""Tests for auth-driven namespace defaulting on search endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthContext, SCOPE_READ_ANY, require_api_key
from app.db.models import ApiKey
from app.db.session import get_db
from app.main import app
from app.services.api_key_service import _hash_key
from app.services.unified_search_service import UnifiedSearchService


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _opt_in(monkeypatch):
    """Default mode for these tests: opt-in, matching dev/CI."""
    from app import auth as auth_mod

    monkeypatch.setattr(auth_mod.settings, "auth_required", False)


def _override_auth(auth: AuthContext) -> None:
    async def _override():
        return auth

    app.dependency_overrides[require_api_key] = _override


def _stub_db():
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return db


def _stub_db_for_auth(row: ApiKey | None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return db


def _row(
    plaintext: str,
    *,
    owner: str = "glazkov",
    scopes: list[str] | None = None,
) -> ApiKey:
    return ApiKey(
        key_id=uuid.uuid4(),
        key_hash=_hash_key(plaintext),
        owner=owner,
        label=None,
        scopes=list(scopes or []),
        created_at=datetime.now(timezone.utc),
        expires_at=None,
        revoked_at=None,
    )


def _auth(owner: str = "glazkov", scopes: set[str] | None = None) -> AuthContext:
    return AuthContext(
        key_id="key",
        owner=owner,
        scopes=frozenset(scopes or set()),
    )


def _hit() -> dict:
    return {
        "entity_id": "entity-1",
        "entity_type": "memory_card",
        "name": "Result",
        "score": 1.0,
        "channel": "latest",
        "version_id": "version-1",
        "tags": [],
        "when_to_use": None,
        "content": {},
        "document_id": None,
        "document_kind": None,
        "snippet": None,
    }


def _captured_search_call(method_name: str = "search"):
    captured: dict = {}

    async def _spy(self, **kwargs):
        captured.update(kwargs)
        return [[_hit()]] if method_name == "batch_search" else [_hit()]

    return captured, _spy


def _first_facet_sql_and_params(db) -> tuple[str, list[object]]:
    first_stmt = db.execute.await_args_list[0].args[0]
    compiled = first_stmt.compile()
    return str(first_stmt), list(compiled.params.values())


def _assert_facet_namespace_filter(db, expected_namespace: str) -> None:
    sql, params = _first_facet_sql_and_params(db)
    assert "entities.namespace" in sql
    assert expected_namespace in params


def _assert_no_facet_namespace_filter(db) -> None:
    sql, params = _first_facet_sql_and_params(db)
    assert "entities.namespace" not in sql
    assert params == []


class TestUnifiedSearchAuthNamespace:
    def test_authenticated_no_namespace_defaults_to_owner(self, client):
        plaintext = "valid-token"
        _stub_db_for_auth(_row(plaintext, owner="glazkov"))
        captured, search_spy = _captured_search_call()

        with patch.object(UnifiedSearchService, "search", new=search_spy):
            response = client.post(
                "/v1/search/unified",
                headers={"X-API-Key": plaintext},
                json={
                    "search_type": "bm25",
                    "query": "test",
                    "entity_type": "memory_card",
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] == "glazkov"

    def test_read_any_no_namespace_keeps_cross_namespace_search(self, client):
        plaintext = "ops-token"
        _stub_db_for_auth(_row(plaintext, scopes=[SCOPE_READ_ANY]))
        captured, search_spy = _captured_search_call()

        with patch.object(UnifiedSearchService, "search", new=search_spy):
            response = client.post(
                "/v1/search/unified",
                headers={"X-API-Key": plaintext},
                json={
                    "search_type": "bm25",
                    "query": "test",
                    "entity_type": "memory_card",
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] is None

    def test_explicit_namespace_wins(self, client):
        _stub_db()
        _override_auth(_auth(owner="glazkov"))
        captured, search_spy = _captured_search_call()

        with patch.object(UnifiedSearchService, "search", new=search_spy):
            response = client.post(
                "/v1/search/unified",
                json={
                    "search_type": "bm25",
                    "query": "test",
                    "entity_type": "memory_card",
                    "namespace": "finance-team",
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] == "finance-team"

    @pytest.mark.parametrize("namespace", ["", "   "])
    def test_blank_namespace_defaults_to_owner(self, client, namespace):
        _stub_db()
        _override_auth(_auth(owner="glazkov"))
        captured, search_spy = _captured_search_call()

        with patch.object(UnifiedSearchService, "search", new=search_spy):
            response = client.post(
                "/v1/search/unified",
                json={
                    "search_type": "bm25",
                    "query": "test",
                    "entity_type": "memory_card",
                    "namespace": namespace,
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] == "glazkov"


class TestBatchSearchAuthNamespace:
    def test_authenticated_no_namespace_defaults_to_owner(self, client):
        _stub_db()
        _override_auth(_auth(owner="glazkov"))
        captured, batch_spy = _captured_search_call("batch_search")

        with patch.object(
            UnifiedSearchService,
            "batch_search",
            new=batch_spy,
        ):
            response = client.post(
                "/v1/search/batch",
                json={
                    "search_type": "bm25",
                    "queries": ["test"],
                    "entity_type": "memory_card",
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] == "glazkov"

    def test_read_any_no_namespace_keeps_cross_namespace_search(self, client):
        _stub_db()
        _override_auth(_auth(scopes={SCOPE_READ_ANY}))
        captured, batch_spy = _captured_search_call("batch_search")

        with patch.object(
            UnifiedSearchService,
            "batch_search",
            new=batch_spy,
        ):
            response = client.post(
                "/v1/search/batch",
                json={
                    "search_type": "bm25",
                    "queries": ["test"],
                    "entity_type": "memory_card",
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] is None

    def test_explicit_namespace_wins(self, client):
        _stub_db()
        _override_auth(_auth(owner="glazkov"))
        captured, batch_spy = _captured_search_call("batch_search")

        with patch.object(
            UnifiedSearchService,
            "batch_search",
            new=batch_spy,
        ):
            response = client.post(
                "/v1/search/batch",
                json={
                    "search_type": "bm25",
                    "queries": ["test"],
                    "entity_type": "memory_card",
                    "namespace": "finance-team",
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] == "finance-team"

    def test_blank_namespace_defaults_to_owner(self, client):
        _stub_db()
        _override_auth(_auth(owner="glazkov"))
        captured, batch_spy = _captured_search_call("batch_search")

        with patch.object(
            UnifiedSearchService,
            "batch_search",
            new=batch_spy,
        ):
            response = client.post(
                "/v1/search/batch",
                json={
                    "search_type": "bm25",
                    "queries": ["test"],
                    "entity_type": "memory_card",
                    "namespace": "",
                },
            )

        assert response.status_code == 200
        assert captured["namespace"] == "glazkov"


class TestFacetsAuthNamespace:
    def test_authenticated_no_namespace_filters_facet_queries_to_owner(self, client):
        db = _stub_db()
        _override_auth(_auth(owner="glazkov"))

        response = client.get("/v1/search/facets")

        assert response.status_code == 200
        _assert_facet_namespace_filter(db, "glazkov")

    def test_read_any_no_namespace_keeps_cross_namespace_facets(self, client):
        db = _stub_db()
        _override_auth(_auth(scopes={SCOPE_READ_ANY}))

        response = client.get("/v1/search/facets")

        assert response.status_code == 200
        _assert_no_facet_namespace_filter(db)

    def test_explicit_namespace_wins(self, client):
        db = _stub_db()
        _override_auth(_auth(owner="glazkov"))

        response = client.get("/v1/search/facets?namespace=finance-team")

        assert response.status_code == 200
        _assert_facet_namespace_filter(db, "finance-team")

    def test_blank_namespace_defaults_to_owner(self, client):
        db = _stub_db()
        _override_auth(_auth(owner="glazkov"))

        response = client.get("/v1/search/facets?namespace=")

        assert response.status_code == 200
        _assert_facet_namespace_filter(db, "glazkov")

    def test_tag_facets_are_aggregated_from_entity_tags(self, client):
        db = AsyncMock()

        def _result(rows):
            result = MagicMock()
            result.all.return_value = rows
            return result

        db.execute = AsyncMock(
            side_effect=[
                _result([("memory_card", 3)]),
                _result([("glazkov", 3)]),
                _result([("collection:weather", 2), ("finance", 1)]),
            ]
        )

        async def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        _override_auth(_auth(owner="glazkov"))

        response = client.get("/v1/search/facets")

        assert response.status_code == 200
        body = response.json()
        assert body["tags"] == {"collection:weather": 2, "finance": 1}
        tag_call = db.execute.await_args_list[2]
        assert tag_call.args[1] == {"namespace": "glazkov"}


class TestSearchStrictMode:
    @pytest.mark.parametrize(
        ("method", "path", "json_body"),
        [
            (
                "post",
                "/v1/search/unified",
                {
                    "search_type": "bm25",
                    "query": "test",
                    "entity_type": "memory_card",
                },
            ),
            (
                "post",
                "/v1/search/batch",
                {
                    "search_type": "bm25",
                    "queries": ["test"],
                    "entity_type": "memory_card",
                },
            ),
            ("get", "/v1/search/facets", None),
        ],
    )
    def test_no_key_returns_401(self, client, monkeypatch, method, path, json_body):
        from app import auth as auth_mod

        monkeypatch.setattr(auth_mod.settings, "auth_required", True)
        _stub_db()

        if method == "post":
            response = client.post(path, json=json_body)
        else:
            response = client.get(path)

        assert response.status_code == 401
