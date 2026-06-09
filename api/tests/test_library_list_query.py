"""Tests for the CARE library list-endpoint query params.

Verifies (without a live DB):
  1. The SQL ``EntityService.list_entities`` emits for each new
     parameter combination uses the correct WHERE / ORDER BY shape.
  2. Cursor pagination is silently dropped when ``sort_by`` differs
     from the default ``created_at`` (so the cursor encoding stays
     meaningful).
  3. The agents router exposes the new query params in its OpenAPI
     surface with the expected defaults and validation patterns.
"""

import re

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.dialects import postgresql


def _render_list_sql(*, literal: bool = True, **kwargs) -> tuple[str, dict]:
    """Capture the SQL emitted by ``EntityService.list_entities``.

    Mocks the AsyncSession so we can inspect ``db.execute(stmt)`` calls
    without a real Postgres. Returns ``(sql_string, params)`` — when
    ``literal=True`` (the default) values are inlined into the SQL;
    when ``False`` (needed for JSONB array params which can't be
    rendered as literals) values land in ``params``.
    """
    from app.services.entity_service import EntityService

    captured: list[tuple[str, dict]] = []

    async def _capture(stmt, *args, **kw):
        compile_kwargs = {"literal_binds": True} if literal else {}
        compiled = stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs=compile_kwargs,
        )
        captured.append((str(compiled), dict(compiled.params)))
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    db = AsyncMock()
    db.execute = _capture
    svc = EntityService(db)

    import asyncio

    asyncio.run(svc.list_entities(channel="latest", **kwargs))
    return captured[0]


def _render_list_sql_str(**kwargs) -> str:
    """Convenience: literal-bound SQL string only (most tests want this)."""
    sql, _ = _render_list_sql(**kwargs)
    return sql


class TestListSortBy:
    """ORDER BY column matches the requested sort field."""

    @pytest.mark.parametrize(
        "sort_by, column",
        [
            ("created_at", "entities.created_at"),
            ("last_run_at", "entities.last_run_at"),
            ("run_count", "entities.run_count"),
            ("display_name", "entities.display_name"),
        ],
    )
    def test_sort_by_each_supported_field(self, sort_by, column):
        sql = _render_list_sql_str(entity_type="agent", sort_by=sort_by)
        assert column in sql, f"sort_by={sort_by} should produce ORDER BY {column}"

    def test_unknown_sort_by_falls_back_to_created_at(self):
        sql = _render_list_sql_str(entity_type="agent", sort_by="not_a_real_column")
        assert "ORDER BY entities.created_at" in sql


class TestListSortDir:
    def test_desc_emits_nulls_last(self):
        sql = _render_list_sql_str(entity_type="agent", sort_by="last_run_at", sort_dir="desc")
        assert "ORDER BY entities.last_run_at DESC" in sql
        assert "NULLS LAST" in sql

    def test_asc_omits_nulls_last(self):
        sql = _render_list_sql_str(entity_type="agent", sort_by="last_run_at", sort_dir="asc")
        assert "ORDER BY entities.last_run_at ASC" in sql
        # ASC default puts NULLs first in Postgres; we don't fight it.
        assert "NULLS LAST" not in sql

    def test_sort_dir_case_insensitive(self):
        sql = _render_list_sql_str(entity_type="agent", sort_dir="DESC")
        assert "entities.created_at DESC" in sql


class TestListFilters:
    def test_favourites_only_adds_predicate(self):
        sql = _render_list_sql_str(entity_type="agent", favourites_only=True)
        # SQLAlchemy compiles `Column.is_(True)` as `IS true` in Postgres.
        assert re.search(r"entities\.favourite\s+IS\s+true", sql) is not None

    def test_favourites_only_default_absent(self):
        sql = _render_list_sql_str(entity_type="agent")
        assert "favourite IS true" not in sql

    def test_namespace_filter(self):
        sql = _render_list_sql_str(entity_type="agent", namespace="glazkov")
        assert "entities.namespace = 'glazkov'" in sql

    def test_tags_uses_jsonb_contains_all_operator(self):
        # JSONB array params can't be rendered as `literal_binds` — fall
        # back to inspecting structure + params.
        sql, params = _render_list_sql(
            entity_type="agent", tags=["pdf", "extraction"], literal=False
        )
        assert "?&" in sql
        # The right operand MUST be cast to a Postgres text[] — without
        # it SQLAlchemy types the list bind as JSONB (inherited from the
        # left column), emitting `jsonb ?& jsonb` which Postgres rejects
        # at runtime with a 500. Guard the cast so the fix can't regress.
        assert "CAST(" in sql.upper()
        assert "AS TEXT[]" in sql.upper()
        # The JSONB ?& bind param appears as a list value.
        assert any(v == ["pdf", "extraction"] for v in params.values())

    def test_empty_tags_list_skips_filter(self):
        sql = _render_list_sql_str(entity_type="agent", tags=[])
        assert "?&" not in sql

    def test_q_emits_ilike_across_three_columns(self):
        # SQLAlchemy doubles `%` to escape pyformat binds — actual SQL
        # over the wire is `ILIKE '%financier%'`; the literal-bound
        # form for inspection is `'%%financier%%'`.
        sql = _render_list_sql_str(entity_type="agent", q="financier")
        assert "ILIKE '%%financier%%'" in sql
        assert "entities.display_name" in sql
        assert "entities.name" in sql
        assert "entities.description" in sql


class TestListCursorInteraction:
    """Cursor pagination only valid when sort matches its encoding."""

    @pytest.mark.asyncio
    async def test_cursor_ignored_with_non_default_sort(self):
        """Non-default sort makes the cursor encoding meaningless — drop silently."""
        from app.services.entity_service import EntityService, _encode_cursor
        import uuid
        from datetime import datetime, timezone

        # Build a syntactically valid cursor (could only have been issued
        # under default sort).
        cursor = _encode_cursor(
            datetime.now(timezone.utc),
            uuid.uuid4(),
            entity_type="agent",
            channel="latest",
        )

        captured: list[str] = []

        async def _capture(stmt, *args, **kw):
            captured.append(
                str(stmt.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                ))
            )
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            return result

        db = AsyncMock()
        db.execute = _capture
        svc = EntityService(db)

        # Default sort: cursor MUST apply.
        await svc.list_entities(entity_type="agent", channel="latest", cursor=cursor)
        default_sql = captured[-1]
        # Non-default sort: cursor MUST be ignored.
        await svc.list_entities(
            entity_type="agent",
            channel="latest",
            cursor=cursor,
            sort_by="last_run_at",
        )
        nondefault_sql = captured[-1]

        # Cursor decode emits `created_at > 'value' OR (created_at = ... AND entity_id > ...)`.
        assert "entities.created_at >" in default_sql
        assert "entities.created_at >" not in nondefault_sql


class TestAgentsListEndpointSurface:
    """The agents router exposes the new query params with the right defaults."""

    def test_openapi_lists_new_query_params(self):
        from app.main import app

        spec = app.openapi()
        params = spec["paths"]["/v1/agents"]["get"]["parameters"]
        names = {p["name"] for p in params}

        assert {
            "sort_by",
            "sort_dir",
            "favourites_only",
            "tags",
            "q",
            "namespace",
        } <= names

    def test_sort_by_default_is_last_run_at(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/agents"]["get"]["parameters"]
        }
        assert params["sort_by"]["schema"]["default"] == "last_run_at"
        assert params["sort_dir"]["schema"]["default"] == "desc"

    def test_sort_by_constrained_to_known_columns(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/agents"]["get"]["parameters"]
        }
        pattern = params["sort_by"]["schema"]["pattern"]
        assert "created_at" in pattern
        assert "last_run_at" in pattern
        assert "run_count" in pattern
        assert "display_name" in pattern
        # Reject arbitrary values.
        assert re.match(pattern, "drop_table") is None

    def test_favourites_only_default_false(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/agents"]["get"]["parameters"]
        }
        assert params["favourites_only"]["schema"]["default"] is False
