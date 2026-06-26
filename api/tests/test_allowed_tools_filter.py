"""Tests for the allowed_tools faceted filter (P2 §4)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import Entity, EntityVersion
from app.routers.agent_skills import (
    _filter_skills_by_tools,
    _skill_tool_tokens,
)


def _entity(name: str = "x") -> Entity:
    return Entity(
        entity_id=uuid.uuid4(),
        entity_type="agent_skill",
        namespace=None,
        name=name,
        tags=[],
        when_to_use=None,
        channels={"latest": str(uuid.uuid4())},
        deleted_at=None,
        favourite=False,
        run_count=0,
        last_run_at=None,
        display_name=name,
        description=None,
    )


def _version(allowed_tools: list[str] | None) -> EntityVersion:
    return EntityVersion(
        version_id=uuid.uuid4(),
        entity_id=uuid.uuid4(),
        version_number=0,
        content_json={"name": "x", "allowed_tools": allowed_tools}
        if allowed_tools is not None
        else {"name": "x"},
        meta_json={},
        parents=None,
        change_summary=None,
        evolution_meta=None,
        author=None,
        created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )


def _pair(name: str, tools: list[str] | None) -> tuple:
    return (_entity(name), _version(tools))


# ---------------------------------------------------------------------------
# _skill_tool_tokens: pure projection
# ---------------------------------------------------------------------------


class TestSkillToolTokens:
    def test_extracts_list(self):
        v = _version(["Bash", "Read"])
        assert _skill_tool_tokens(v) == ["Bash", "Read"]

    def test_empty_when_missing(self):
        v = _version(None)
        assert _skill_tool_tokens(v) == []

    def test_empty_when_not_a_list(self):
        v = EntityVersion(
            version_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            version_number=0,
            content_json={"allowed_tools": "Bash,Read"},  # malformed: not a list
            meta_json={},
            parents=None,
            change_summary=None,
            evolution_meta=None,
            author=None,
            created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
        )
        assert _skill_tool_tokens(v) == []

    def test_empty_when_content_is_none(self):
        v = EntityVersion(
            version_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            version_number=0,
            content_json={},
            meta_json={},
            parents=None,
            change_summary=None,
            evolution_meta=None,
            author=None,
            created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
        )
        v.content_json = None  # type: ignore[assignment]
        assert _skill_tool_tokens(v) == []


# ---------------------------------------------------------------------------
# _filter_skills_by_tools
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog() -> list[tuple]:
    """A small mixed catalogue covering common allowed_tools shapes."""
    return [
        _pair("pdf",     ["Bash(python:*)", "Read", "Write"]),
        _pair("pptx",    ["Bash(python:*)", "Read", "Write"]),
        _pair("weather", ["WebFetch(domain:api.openweathermap.org)"]),
        _pair("notes",   ["Read", "Write"]),
        _pair("untagged", None),  # no allowed_tools at all
    ]


class TestFilterSkillsByTools:
    def test_no_filters_passthrough(self, catalog):
        assert _filter_skills_by_tools(catalog, requires_tool=None, excludes_tool=None) == catalog
        assert _filter_skills_by_tools(catalog, requires_tool=[], excludes_tool=[]) == catalog

    def test_requires_single_token(self, catalog):
        """Keep skills that need WebFetch."""
        out = _filter_skills_by_tools(
            catalog,
            requires_tool=["WebFetch(domain:api.openweathermap.org)"],
            excludes_tool=None,
        )
        assert [e.name for e, _ in out] == ["weather"]

    def test_requires_multiple_tokens_AND_semantics(self, catalog):
        """Need BOTH Read AND Write — drops weather, keeps the rest with
        those tokens."""
        out = _filter_skills_by_tools(
            catalog, requires_tool=["Read", "Write"], excludes_tool=None
        )
        assert {e.name for e, _ in out} == {"pdf", "pptx", "notes"}

    def test_requires_tool_missing_in_any_drops_all_unsatisfied(self, catalog):
        """A skill missing one required token is dropped entirely."""
        out = _filter_skills_by_tools(
            catalog,
            requires_tool=["WebFetch(domain:api.openweathermap.org)", "Read"],
            excludes_tool=None,
        )
        # Only `weather` has the WebFetch token but it lacks `Read`.
        assert out == []

    def test_excludes_single_token(self, catalog):
        """Drop skills that mention Bash — the canonical CARE use case."""
        out = _filter_skills_by_tools(
            catalog, requires_tool=None, excludes_tool=["Bash(python:*)"]
        )
        assert {e.name for e, _ in out} == {"weather", "notes", "untagged"}

    def test_excludes_multiple_tokens_OR_semantics(self, catalog):
        """Drop skills that mention ANY excluded token."""
        out = _filter_skills_by_tools(
            catalog, requires_tool=None,
            excludes_tool=["Bash(python:*)", "WebFetch(domain:api.openweathermap.org)"],
        )
        # Only notes (Read/Write only) and untagged (no tools at all) remain.
        assert {e.name for e, _ in out} == {"notes", "untagged"}

    def test_requires_combined_with_excludes(self, catalog):
        """AND-combined: 'requires Read AND Write AND NOT Bash'."""
        out = _filter_skills_by_tools(
            catalog,
            requires_tool=["Read", "Write"],
            excludes_tool=["Bash(python:*)"],
        )
        assert {e.name for e, _ in out} == {"notes"}

    def test_untagged_skill_satisfies_excludes_but_not_requires(self, catalog):
        """A skill with no allowed_tools is dropped by ANY require but
        survives every exclude."""
        # require → drops untagged
        out_req = _filter_skills_by_tools(
            catalog, requires_tool=["Read"], excludes_tool=None
        )
        assert "untagged" not in {e.name for e, _ in out_req}

        # exclude → keeps untagged
        out_exc = _filter_skills_by_tools(
            catalog, requires_tool=None, excludes_tool=["Bash(python:*)"]
        )
        assert "untagged" in {e.name for e, _ in out_exc}

    def test_filter_preserves_input_order(self, catalog):
        """The post-filter must not reshuffle — the upstream service
        already applied the requested sort order."""
        out = _filter_skills_by_tools(
            catalog, requires_tool=["Read"], excludes_tool=None
        )
        names = [e.name for e, _ in out]
        # pdf comes before pptx in the catalogue; both have Read.
        # The relative order pdf → pptx → notes is preserved.
        assert names == ["pdf", "pptx", "notes"]


# ---------------------------------------------------------------------------
# Router wiring
# ---------------------------------------------------------------------------


class TestRouterParams:
    def test_openapi_exposes_new_params(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/agent-skills"]["get"]["parameters"]
        }
        assert "requires_tool" in params
        assert "excludes_tool" in params

    def test_params_accept_list_of_strings(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/agent-skills"]["get"]["parameters"]
        }
        # Both params are list[str] | None — FastAPI renders as anyOf
        # of array[str] and null in the schema.
        for name in ("requires_tool", "excludes_tool"):
            s = params[name]["schema"]
            # Accept either pure array shape or anyOf-with-null.
            shapes = s.get("anyOf", [s])
            assert any(
                shape.get("type") == "array"
                and shape.get("items", {}).get("type") == "string"
                for shape in shapes
            )


class TestRouterPostFilter:
    """End-to-end: the route fetches a larger window when filters are
    active and trims the result down to `limit` after the post-filter."""

    @pytest.mark.asyncio
    async def test_fetch_multiplier_applied_when_filters_active(self):
        """When `requires_tool` or `excludes_tool` is set, the router
        asks list_entities for ``limit * 4`` candidates (capped at 200)."""
        from app.routers import agent_skills as ar

        # Stub: returns 1 candidate (won't matter for the assertion —
        # we only check the limit argument).
        captured_limit = {}

        async def _fake_list(**kw):
            captured_limit["limit"] = kw["limit"]
            return [], None, False

        with MagicMock() as _m:
            svc = MagicMock()
            svc.list_entities = _fake_list

            class _Svc:
                def __init__(self, db):
                    pass

                list_entities = staticmethod(_fake_list)

            old_cls = ar.EntityService
            ar.EntityService = _Svc  # type: ignore[assignment]
            try:
                # Drive the route function directly.
                from fastapi.testclient import TestClient
                from app.main import app
                from app.db.session import get_db

                async def _override_db():
                    yield AsyncMock()

                app.dependency_overrides[get_db] = _override_db
                try:
                    client = TestClient(app)
                    client.get(
                        "/v1/agent-skills",
                        params={"limit": 10, "requires_tool": "Read"},
                    )
                    assert captured_limit["limit"] == 40
                finally:
                    app.dependency_overrides.clear()
            finally:
                ar.EntityService = old_cls  # type: ignore[assignment]

    @pytest.mark.asyncio
    async def test_no_multiplier_without_filters(self):
        from app.routers import agent_skills as ar

        captured_limit = {}

        async def _fake_list(**kw):
            captured_limit["limit"] = kw["limit"]
            return [], None, False

        class _Svc:
            def __init__(self, db):
                pass

            list_entities = staticmethod(_fake_list)

        old_cls = ar.EntityService
        ar.EntityService = _Svc  # type: ignore[assignment]
        try:
            from fastapi.testclient import TestClient
            from app.main import app
            from app.db.session import get_db

            async def _override_db():
                yield AsyncMock()

            app.dependency_overrides[get_db] = _override_db
            try:
                client = TestClient(app)
                client.get("/v1/agent-skills", params={"limit": 10})
                assert captured_limit["limit"] == 10  # no multiplier
            finally:
                app.dependency_overrides.clear()
        finally:
            ar.EntityService = old_cls  # type: ignore[assignment]
