"""Tests for the browser-friendly diff renderer + ?format=html endpoint
(TODO §8 P3).

Three layers:
  1. ``render_diff_html`` — pure function, no FastAPI / DB.
  2. ``GET /v1/{type}/{id}/diff`` JSON shape unchanged (regression guard).
  3. ``GET /v1/{type}/{id}/diff?format=html`` returns text/html with the
     expected page structure.

Both endpoint tests use TestClient against the real app with a
DB-session override — no Postgres needed.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.services.diff_html import (
    _format_value,
    _normalise_patch,
    _summarise,
    render_diff_html,
)


# ---------------------------------------------------------------------------
# Pure renderer
# ---------------------------------------------------------------------------


class TestNormalisePatch:
    def test_already_a_list_of_dicts(self):
        ops = [{"op": "replace", "path": "/x", "value": 2}]
        assert _normalise_patch(ops) == ops

    def test_json_string(self):
        ops = [{"op": "add", "path": "/a", "value": 1}]
        assert _normalise_patch(json.dumps(ops)) == ops

    def test_empty_string(self):
        assert _normalise_patch("") == []

    def test_malformed_string_returns_empty(self):
        """The renderer must never raise on garbage — fall back to no-ops."""
        assert _normalise_patch("not-json{[") == []

    def test_non_list_value_returns_empty(self):
        assert _normalise_patch({"ops": []}) == []

    def test_drops_non_dict_entries(self):
        ops = [{"op": "add", "path": "/a", "value": 1}, "garbage", 42]
        assert _normalise_patch(ops) == [{"op": "add", "path": "/a", "value": 1}]


class TestFormatValue:
    def test_none_renders_null(self):
        assert _format_value(None) == "null"

    def test_scalar_string_quoted(self):
        assert _format_value("hello") == "&quot;hello&quot;"

    def test_dict_pretty_printed(self):
        result = _format_value({"b": 2, "a": 1})
        assert "&quot;a&quot;: 1" in result and "&quot;b&quot;: 2" in result

    def test_escapes_html_in_value(self):
        """A maliciously-crafted value must not break out of the page."""
        result = _format_value("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


class TestSummarise:
    def test_counts_known_ops(self):
        counts = _summarise([
            {"op": "add", "path": "/a"},
            {"op": "add", "path": "/b"},
            {"op": "remove", "path": "/c"},
            {"op": "replace", "path": "/d"},
        ])
        assert counts["add"] == 2
        assert counts["remove"] == 1
        assert counts["replace"] == 1
        assert counts["move"] == 0

    def test_ignores_unknown_ops(self):
        counts = _summarise([{"op": "unknown", "path": "/x"}])
        assert all(v == 0 for v in counts.values())


class TestRenderDiffHtml:
    SAMPLE = [
        {"op": "add", "path": "/steps/2", "value": {"name": "summarise"}},
        {"op": "remove", "path": "/steps/0"},
        {"op": "replace", "path": "/max_workers", "value": 4},
        {"op": "move", "from": "/steps/1", "path": "/steps/0"},
    ]

    def _render(self, patch=None, **overrides):
        defaults = dict(
            entity_type="chain",
            entity_id="3d2bd07e-2a02-4f25-9d51-2c8f7e8f6c8a",
            from_version="v-old",
            to_version="v-new",
            patch=patch if patch is not None else self.SAMPLE,
        )
        defaults.update(overrides)
        return render_diff_html(**defaults)

    def test_returns_complete_html_doc(self):
        out = self._render()
        assert out.startswith("<!doctype html>")
        assert "</html>" in out

    def test_carries_inline_css(self):
        """Self-contained: no external assets, no fetch."""
        out = self._render()
        assert "<style>" in out
        assert "</style>" in out
        # No external links.
        assert 'rel="stylesheet"' not in out
        assert '<script' not in out

    def test_header_carries_metadata(self):
        out = self._render()
        for needle in ("chain", "3d2bd07e", "v-old", "v-new"):
            assert needle in out, needle

    def test_each_op_rendered_as_row(self):
        out = self._render()
        for kind in ("add", "remove", "replace", "move"):
            assert f'class="row {kind}"' in out, kind

    def test_path_shown_for_each_op(self):
        out = self._render()
        for path in ("/steps/2", "/steps/0", "/max_workers"):
            assert path in out, path

    def test_summary_chips_count_ops(self):
        out = self._render()
        # 1 add, 1 remove, 1 replace, 1 move.
        assert "1 add" in out
        assert "1 remove" in out
        assert "1 replace" in out
        assert "1 move" in out

    def test_empty_patch_renders_no_changes_state(self):
        out = self._render(patch=[])
        assert "no changes" in out.lower() or "identical" in out.lower()

    def test_value_field_escaped(self):
        """User-controlled content (e.g. chain steps holding a comment
        that quotes JS) must be HTML-escaped — never executed."""
        evil = [{"op": "replace", "path": "/p", "value": "<img src=x onerror=alert(1)>"}]
        out = self._render(patch=evil)
        assert "<img src=x" not in out
        assert "&lt;img src=x onerror=alert(1)&gt;" in out

    def test_path_escaped(self):
        evil = [{"op": "add", "path": "/<script>", "value": 1}]
        out = self._render(patch=evil)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_accepts_patch_as_json_string(self):
        """The endpoint passes the raw `.to_string()` output through —
        the renderer must parse it."""
        out = self._render(patch=json.dumps(self.SAMPLE))
        for path in ("/steps/2", "/max_workers"):
            assert path in out, path

    def test_move_op_shows_from_field(self):
        out = self._render()
        # The "move" op carries a "from" pointer — must surface.
        assert "from" in out and "/steps/1" in out


# ---------------------------------------------------------------------------
# Endpoint: JSON path (regression guard)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_db(monkeypatch):
    """Override the ``get_db`` dependency with a no-op session.

    The actual diff is exercised through ``EntityService.diff_versions``
    which we monkey-patch on a per-test basis below.
    """
    async def _get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def _stub_diff(monkeypatch, return_value):
    from app.services import entity_service

    async def fake_diff(self, from_v, to_v):
        return return_value

    monkeypatch.setattr(entity_service.EntityService, "diff_versions", fake_diff)


class TestEndpointJson:
    def test_default_format_is_json(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, {
            "from_version": "v-1",
            "to_version": "v-2",
            "patch": json.dumps([{"op": "add", "path": "/a", "value": 1}]),
        })
        client = TestClient(app)
        eid = str(uuid.uuid4())
        r = client.get(
            f"/v1/chains/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        body = r.json()
        assert body["from_version"] == "v-1"
        assert body["to_version"] == "v-2"
        assert "ops" in body["patch"]

    def test_explicit_format_json(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, {
            "from_version": "v-1", "to_version": "v-2",
            "patch": json.dumps([]),
        })
        client = TestClient(app)
        eid = str(uuid.uuid4())
        r = client.get(
            f"/v1/chains/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4()), "format": "json"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")

    def test_missing_version_returns_404(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, None)
        client = TestClient(app)
        eid = str(uuid.uuid4())
        r = client.get(
            f"/v1/chains/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4())},
        )
        assert r.status_code == 404

    def test_invalid_entity_type_400(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, {
            "from_version": "v-1", "to_version": "v-2",
            "patch": json.dumps([]),
        })
        client = TestClient(app)
        eid = str(uuid.uuid4())
        r = client.get(
            f"/v1/widgets/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4())},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Endpoint: HTML path
# ---------------------------------------------------------------------------


class TestEndpointHtml:
    def test_html_format_returns_text_html(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, {
            "from_version": "v-1", "to_version": "v-2",
            "patch": json.dumps([
                {"op": "replace", "path": "/max_workers", "value": 4},
            ]),
        })
        client = TestClient(app)
        eid = str(uuid.uuid4())
        r = client.get(
            f"/v1/chains/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4()), "format": "html"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        body = r.text
        assert body.startswith("<!doctype html>")
        assert "/max_workers" in body
        assert "1 replace" in body

    def test_html_uses_path_eid_in_header(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, {
            "from_version": "v-1", "to_version": "v-2",
            "patch": json.dumps([]),
        })
        client = TestClient(app)
        eid = uuid.UUID("3d2bd07e-2a02-4f25-9d51-2c8f7e8f6c8a")
        r = client.get(
            f"/v1/chains/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4()), "format": "html"},
        )
        assert r.status_code == 200
        # The entity_id from the path should appear in the rendered header.
        assert str(eid) in r.text

    def test_html_404_when_versions_missing(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, None)
        client = TestClient(app)
        eid = str(uuid.uuid4())
        r = client.get(
            f"/v1/chains/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4()), "format": "html"},
        )
        assert r.status_code == 404

    def test_invalid_format_rejected(self, stub_db, monkeypatch):
        _stub_diff(monkeypatch, {
            "from_version": "v-1", "to_version": "v-2", "patch": "[]",
        })
        client = TestClient(app)
        eid = str(uuid.uuid4())
        r = client.get(
            f"/v1/chains/{eid}/diff",
            params={"from": str(uuid.uuid4()), "to": str(uuid.uuid4()), "format": "xml"},
        )
        assert r.status_code == 422
