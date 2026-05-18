"""Tests for the library-metadata formatters used by the Gradio
Chains and Agents pages (iter #45, §1 P1).

Three layers:
  1. ``format_favourite`` — star glyph for truthy / empty for falsy.
  2. ``pick_display_name`` — user-edited display_name beats
     meta['name'] which beats "N/A".
  3. ``format_last_run`` — compact relative time ("5m ago" etc.).

Also covers ``MemoryClientWrapper._entity_to_dict`` exposing the
library fields. Standalone tests — no gradio import needed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make ``web_ui.app.library_format`` importable. The web_ui isn't a
# packaged distribution; the Gradio entry point adjusts sys.path at
# runtime, so the test does the same here.
_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))
# The wrapper file imports gigaevo_client at module top — make sure
# the SDK source is reachable too.
sys.path.insert(0, str(_repo_root / "client" / "python" / "src"))

from web_ui.app.library_format import (  # noqa: E402
    format_favourite,
    format_last_run,
    pick_display_name,
)


# ---------------------------------------------------------------------------
# format_favourite
# ---------------------------------------------------------------------------


class TestFormatFavourite:
    def test_true_renders_star(self):
        assert format_favourite(True) == "⭐"

    def test_false_renders_empty(self):
        assert format_favourite(False) == ""

    def test_none_renders_empty(self):
        assert format_favourite(None) == ""

    def test_truthy_strings_render_star(self):
        """The server's response may carry "true" / 1 across JSON —
        the UI shouldn't be picky about exact bool."""
        assert format_favourite(1) == "⭐"
        assert format_favourite("yes") == "⭐"

    def test_empty_string_renders_empty(self):
        assert format_favourite("") == ""


# ---------------------------------------------------------------------------
# pick_display_name
# ---------------------------------------------------------------------------


class TestPickDisplayName:
    def test_display_name_wins_over_meta_name(self):
        assert (
            pick_display_name({"name": "url-safe-name"}, "Pretty Display")
            == "Pretty Display"
        )

    def test_meta_name_used_when_no_display_name(self):
        assert pick_display_name({"name": "url-safe-name"}, None) == "url-safe-name"

    def test_empty_display_name_falls_back(self):
        assert pick_display_name({"name": "url-safe"}, "") == "url-safe"

    def test_no_display_name_no_meta_name_returns_na(self):
        assert pick_display_name({}, None) == "N/A"
        assert pick_display_name(None, None) == "N/A"

    def test_non_dict_meta_returns_na(self):
        """A malformed meta (rare; server bug) shouldn't crash the UI."""
        assert pick_display_name("not-a-dict", None) == "N/A"

    def test_display_name_coerced_to_string(self):
        """Defensive: server could in theory return a non-string."""
        assert pick_display_name({}, 42) == "42"


# ---------------------------------------------------------------------------
# format_last_run
# ---------------------------------------------------------------------------


class TestFormatLastRun:
    NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)

    def test_none_renders_em_dash(self):
        assert format_last_run(None, now=self.NOW) == "—"

    def test_empty_string_renders_em_dash(self):
        assert format_last_run("", now=self.NOW) == "—"

    def test_just_now(self):
        ts = (self.NOW - timedelta(seconds=10)).isoformat()
        assert format_last_run(ts, now=self.NOW) == "just now"

    def test_minutes_ago(self):
        ts = (self.NOW - timedelta(minutes=5)).isoformat()
        assert format_last_run(ts, now=self.NOW) == "5m ago"

    def test_hours_ago(self):
        ts = (self.NOW - timedelta(hours=3)).isoformat()
        assert format_last_run(ts, now=self.NOW) == "3h ago"

    def test_days_ago(self):
        ts = (self.NOW - timedelta(days=4)).isoformat()
        assert format_last_run(ts, now=self.NOW) == "4d ago"

    def test_thirty_plus_days_falls_back_to_iso_date(self):
        """Anything older than 30 days carries less info as 'Xd ago'
        than as an absolute date."""
        ts = (self.NOW - timedelta(days=45)).isoformat()
        result = format_last_run(ts, now=self.NOW)
        # 2026-05-16 minus 45 days = 2026-04-01
        assert result == "2026-04-01"

    def test_accepts_datetime_directly(self):
        dt = self.NOW - timedelta(minutes=10)
        assert format_last_run(dt, now=self.NOW) == "10m ago"

    def test_naive_datetime_treated_as_utc(self):
        """Server may return a naive datetime when not tz-aware; we
        treat it as UTC so the math still works."""
        naive = (self.NOW - timedelta(minutes=10)).replace(tzinfo=None)
        assert format_last_run(naive, now=self.NOW) == "10m ago"

    def test_invalid_string_returns_original(self):
        """A non-ISO string surfaces as-is so the UI doesn't hide bugs."""
        assert format_last_run("not a date", now=self.NOW) == "not a date"

    def test_boundary_60s(self):
        """Exactly 60s → first minute bucket."""
        ts = (self.NOW - timedelta(seconds=60)).isoformat()
        assert format_last_run(ts, now=self.NOW) == "1m ago"

    def test_boundary_30d(self):
        """Exactly 30 days → ISO date threshold."""
        ts = (self.NOW - timedelta(days=30)).isoformat()
        assert format_last_run(ts, now=self.NOW) == "2026-04-16"


# ---------------------------------------------------------------------------
# Wrapper integration: _entity_to_dict surfaces library fields
# ---------------------------------------------------------------------------


class TestEntityToDict:
    """Confirm ``MemoryClientWrapper._entity_to_dict`` returns the
    five new library fields. Skipped when the wrapper can't be
    imported (gigaevo_client missing from sys.path)."""

    @pytest.fixture
    def wrapper_class(self):
        from web_ui.app.client import MemoryClientWrapper
        return MemoryClientWrapper

    def _entity(self, **overrides):
        e = MagicMock()
        e.entity_id = "agent-42"
        e.entity_type = "agent"
        e.version_id = "v1"
        e.channel = "latest"
        e.etag = "abc"
        e.meta = {"name": "Researcher"}
        e.content = {"x": 1}
        e.favourite = True
        e.run_count = 7
        e.last_run_at = datetime(2026, 5, 15, 10, 0, 0, tzinfo=timezone.utc)
        e.display_name = "Researcher (pretty)"
        e.description = "A research agent"
        for k, v in overrides.items():
            setattr(e, k, v)
        return e

    def test_dict_includes_library_fields(self, wrapper_class):
        wrapper = wrapper_class.__new__(wrapper_class)  # bypass __init__
        d = wrapper._entity_to_dict(self._entity())
        assert d["favourite"] is True
        assert d["run_count"] == 7
        assert d["last_run_at"] == "2026-05-15T10:00:00+00:00"
        assert d["display_name"] == "Researcher (pretty)"
        assert d["description"] == "A research agent"

    def test_dict_keeps_legacy_fields(self, wrapper_class):
        wrapper = wrapper_class.__new__(wrapper_class)
        d = wrapper._entity_to_dict(self._entity())
        assert d["entity_id"] == "agent-42"
        assert d["meta"] == {"name": "Researcher"}
        assert d["content"] == {"x": 1}

    def test_dict_defaults_when_fields_missing(self, wrapper_class):
        """Older responses without the iter #11 fields shouldn't blow
        up — defaults kick in."""
        wrapper = wrapper_class.__new__(wrapper_class)
        bare = MagicMock(spec=[
            "entity_id", "entity_type", "version_id", "channel", "etag",
            "meta", "content",
        ])
        bare.entity_id = "x"
        bare.entity_type = "agent"
        bare.version_id = "v"
        bare.channel = "latest"
        bare.etag = "e"
        bare.meta = {}
        bare.content = {}
        d = wrapper._entity_to_dict(bare)
        assert d["favourite"] is False
        assert d["run_count"] == 0
        assert d["last_run_at"] is None
        assert d["display_name"] is None
        assert d["description"] is None

    def test_dict_last_run_at_none_serialises_to_none(self, wrapper_class):
        wrapper = wrapper_class.__new__(wrapper_class)
        d = wrapper._entity_to_dict(self._entity(last_run_at=None))
        assert d["last_run_at"] is None


# ---------------------------------------------------------------------------
# End-to-end: simulated load_agents pipeline produces a 7-column row
# ---------------------------------------------------------------------------


class TestRenderingPipeline:
    """Walks the formatters in the order the Gradio page uses them
    to confirm a representative agent entity produces the expected
    7-column table row."""

    def test_favourite_agent_with_recent_run(self):
        now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        agent = {
            "entity_id": "agent-1",
            "meta": {"name": "url-safe", "tags": ["finance", "ops"]},
            "channel": "latest",
            "version_id": "ver-abc12345",
            "favourite": True,
            "last_run_at": (now - timedelta(minutes=12)).isoformat(),
            "display_name": "Finance Bot",
        }
        # Mirror the same order the agents page builds:
        row = [
            format_favourite(agent.get("favourite")),
            agent["entity_id"],
            pick_display_name(agent["meta"], agent.get("display_name")),
            format_last_run(agent.get("last_run_at"), now=now),
            agent["channel"],
            agent["version_id"][:8],
            ", ".join(agent["meta"]["tags"]),
        ]
        assert row == [
            "⭐", "agent-1", "Finance Bot", "12m ago", "latest",
            "ver-abc1", "finance, ops",
        ]

    def test_non_favourite_no_run(self):
        agent = {
            "entity_id": "agent-2",
            "meta": {"name": "n", "tags": []},
            "channel": "latest",
            "version_id": "v",
            "favourite": False,
            "last_run_at": None,
            "display_name": None,
        }
        row = [
            format_favourite(agent.get("favourite")),
            agent["entity_id"],
            pick_display_name(agent["meta"], agent.get("display_name")),
            format_last_run(agent.get("last_run_at")),
            agent["channel"],
            agent["version_id"][:8],
            ", ".join(agent["meta"]["tags"]),
        ]
        assert row == ["", "agent-2", "n", "—", "latest", "v", ""]
