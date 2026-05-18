"""Tests for ``EntityService.get_lineage`` + ``GET /v1/chains/{id}/lineage``.

The service walks ``entity_versions.parents`` BFS-style from a starting
version. Tests build canned `EntityVersion` objects with parent UUIDs
linking them, mock the DB so each `WHERE version_id IN (...)` call
returns the right subset.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import Entity, EntityVersion
from app.services.entity_service import EntityService


def _ver(
    version_id: uuid.UUID,
    entity_id: uuid.UUID,
    *,
    version_number: int = 0,
    parents: list[uuid.UUID] | None = None,
    evolution_meta: dict | None = None,
    change_summary: str | None = None,
    author: str | None = None,
) -> EntityVersion:
    return EntityVersion(
        version_id=version_id,
        entity_id=entity_id,
        version_number=version_number,
        content_json={},
        meta_json={},
        parents=list(parents) if parents else None,
        change_summary=change_summary,
        evolution_meta=evolution_meta,
        author=author,
        created_at=datetime(2026, 5, 16, 12, version_number, tzinfo=timezone.utc),
    )


def _entity(entity_id: uuid.UUID, latest_version_id: uuid.UUID) -> Entity:
    return Entity(
        entity_id=entity_id,
        entity_type="chain",
        namespace="glazkov",
        name="x",
        tags=[],
        when_to_use=None,
        channels={"latest": str(latest_version_id)},
        deleted_at=None,
        favourite=False,
        run_count=0,
        last_run_at=None,
        display_name="x",
        description=None,
    )


def _build_mock_db(
    entity: Entity | None,
    versions_by_id: dict[uuid.UUID, EntityVersion],
) -> AsyncMock:
    """Build a DB mock that handles the queries `get_lineage` issues.

    Inspects the SQL's FROM clause to discriminate Entity from
    EntityVersion queries; for version queries, recursively walks the
    statement's WHERE-clause UUID bind parameters to pick out the
    matching versions from ``versions_by_id``.
    """
    db = AsyncMock()

    def _collect_uuid_binds(stmt) -> set[uuid.UUID]:
        """Walk the parameter binds of a compiled stmt and return any
        UUIDs (single equals OR in-list)."""
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        out: set[uuid.UUID] = set()
        for val in compiled.params.values():
            if isinstance(val, uuid.UUID):
                out.add(val)
            elif isinstance(val, (list, tuple)):
                for v in val:
                    if isinstance(v, uuid.UUID):
                        out.add(v)
        return out

    async def _execute(stmt):
        compiled_sql = str(stmt)
        result = MagicMock()

        if "entities" in compiled_sql and "entity_versions" not in compiled_sql:
            # Entity SELECT (single).
            result.scalar_one_or_none = MagicMock(return_value=entity)
            return result

        # entity_versions query — figure out which UUIDs are requested.
        requested = _collect_uuid_binds(stmt)
        matched = [versions_by_id[u] for u in requested if u in versions_by_id]

        scalars = MagicMock()
        scalars.all = MagicMock(return_value=matched)
        result.scalars = MagicMock(return_value=scalars)
        result.scalar_one_or_none = MagicMock(
            return_value=matched[0] if matched else None
        )
        return result

    db.execute = _execute
    return db


class TestGetLineageBasics:
    @pytest.mark.asyncio
    async def test_returns_none_when_entity_missing(self):
        db = _build_mock_db(None, {})
        out = await EntityService(db).get_lineage(uuid.uuid4())
        assert out is None

    @pytest.mark.asyncio
    async def test_root_only_when_no_parents(self):
        entity_id = uuid.uuid4()
        v0 = uuid.uuid4()
        entity = _entity(entity_id, v0)
        versions = {v0: _ver(v0, entity_id, version_number=0)}
        db = _build_mock_db(entity, versions)

        out = await EntityService(db).get_lineage(entity_id)
        assert out is not None
        assert out["entity_id"] == str(entity_id)
        assert out["root_version_id"] == str(v0)
        assert len(out["versions"]) == 1
        assert out["versions"][0]["depth"] == 0
        assert out["versions"][0]["parents"] == []
        assert out["max_depth_reached"] is False


class TestGetLineageBFS:
    @pytest.mark.asyncio
    async def test_walks_single_parent_chain(self):
        entity_id = uuid.uuid4()
        v0 = uuid.uuid4()  # root
        v1 = uuid.uuid4()  # parent
        v2 = uuid.uuid4()  # grandparent
        entity = _entity(entity_id, v0)
        versions = {
            v0: _ver(v0, entity_id, version_number=2, parents=[v1]),
            v1: _ver(v1, entity_id, version_number=1, parents=[v2]),
            v2: _ver(v2, entity_id, version_number=0, parents=None),
        }
        db = _build_mock_db(entity, versions)

        out = await EntityService(db).get_lineage(entity_id, max_depth=10)
        assert out is not None
        depths = {v["version_id"]: v["depth"] for v in out["versions"]}
        assert depths[str(v0)] == 0
        assert depths[str(v1)] == 1
        assert depths[str(v2)] == 2
        # Order: root first, then by depth.
        assert out["versions"][0]["version_id"] == str(v0)
        assert out["max_depth_reached"] is False

    @pytest.mark.asyncio
    async def test_dedup_diamond_crossover(self):
        """A & B → C → D; lineage from D includes C, A, B exactly once."""
        entity_id = uuid.uuid4()
        d = uuid.uuid4()
        c = uuid.uuid4()
        a = uuid.uuid4()
        b = uuid.uuid4()
        entity = _entity(entity_id, d)
        versions = {
            d: _ver(d, entity_id, version_number=3, parents=[c]),
            c: _ver(c, entity_id, version_number=2, parents=[a, b]),
            a: _ver(a, entity_id, version_number=1, parents=None),
            b: _ver(b, entity_id, version_number=0, parents=None),
        }
        db = _build_mock_db(entity, versions)

        out = await EntityService(db).get_lineage(entity_id)
        ids = [v["version_id"] for v in out["versions"]]
        # Four distinct versions, deduped.
        assert sorted(ids) == sorted([str(x) for x in (d, c, a, b)])
        # Depths.
        depths = {v["version_id"]: v["depth"] for v in out["versions"]}
        assert depths[str(d)] == 0
        assert depths[str(c)] == 1
        assert depths[str(a)] == 2
        assert depths[str(b)] == 2

    @pytest.mark.asyncio
    async def test_max_depth_caps_walk(self):
        """``max_depth=1`` returns root + immediate parents only."""
        entity_id = uuid.uuid4()
        v0 = uuid.uuid4()
        v1 = uuid.uuid4()
        v2 = uuid.uuid4()
        entity = _entity(entity_id, v0)
        versions = {
            v0: _ver(v0, entity_id, version_number=2, parents=[v1]),
            v1: _ver(v1, entity_id, version_number=1, parents=[v2]),
            v2: _ver(v2, entity_id, version_number=0, parents=None),
        }
        db = _build_mock_db(entity, versions)

        out = await EntityService(db).get_lineage(entity_id, max_depth=1)
        ids = {v["version_id"] for v in out["versions"]}
        assert ids == {str(v0), str(v1)}
        # Grandparent v2 is reachable but cap stopped us.
        assert out["max_depth_reached"] is True


class TestGetLineageVersionIdParameter:
    @pytest.mark.asyncio
    async def test_walks_from_specific_version_id(self):
        entity_id = uuid.uuid4()
        v0 = uuid.uuid4()  # head
        v1 = uuid.uuid4()  # historical, what we walk from
        v2 = uuid.uuid4()  # ancestor of v1
        entity = _entity(entity_id, v0)
        versions = {
            v0: _ver(v0, entity_id, version_number=2, parents=[v1]),
            v1: _ver(v1, entity_id, version_number=1, parents=[v2]),
            v2: _ver(v2, entity_id, version_number=0, parents=None),
        }
        db = _build_mock_db(entity, versions)

        out = await EntityService(db).get_lineage(entity_id, version_id=v1)
        assert out is not None
        assert out["root_version_id"] == str(v1)
        # v0 is NOT in the result (it's a descendant of v1, not an ancestor).
        ids = {v["version_id"] for v in out["versions"]}
        assert str(v0) not in ids
        assert ids == {str(v1), str(v2)}

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_version_id(self):
        entity_id = uuid.uuid4()
        v0 = uuid.uuid4()
        entity = _entity(entity_id, v0)
        versions = {v0: _ver(v0, entity_id)}
        db = _build_mock_db(entity, versions)

        out = await EntityService(db).get_lineage(
            entity_id, version_id=uuid.uuid4()  # not in versions dict
        )
        assert out is None


class TestRouterRegistration:
    def test_chain_router_exposes_lineage(self):
        from app.routers.chains import router

        paths_methods = {
            (route.path, method)
            for route in router.routes
            for method in getattr(route, "methods", ())
        }
        assert ("/v1/chains/{chain_id}/lineage", "GET") in paths_methods

    def test_openapi_describes_response(self):
        from app.main import app

        schema = app.openapi()
        assert "/v1/chains/{chain_id}/lineage" in schema["paths"]
        components = schema["components"]["schemas"]
        assert "LineageResponse" in components
        assert "LineageVersion" in components
        # The 4 documented response fields.
        for f in ("entity_id", "root_version_id", "versions", "max_depth_reached"):
            assert f in components["LineageResponse"]["properties"]

    def test_max_depth_constrained(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/chains/{chain_id}/lineage"]["get"]["parameters"]
        }
        depth_schema = params["max_depth"]["schema"]
        assert depth_schema.get("minimum") == 1
        assert depth_schema.get("maximum") == 100
        assert depth_schema.get("default") == 10
