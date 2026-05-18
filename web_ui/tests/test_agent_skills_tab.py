"""Tests for the AgentSkills Gradio tab (TODO §1.2 P1).

Three layers:
  1. ``MemoryClientWrapper`` exposes ``get_agent_skills`` / ``get_agent_skill``
     / ``save_agent_skill`` / ``delete_agent_skill`` and routes them to the
     matching ``gigaevo_client`` SDK methods.
  2. ``EntityTypeConfig`` knows about ``agent_skills``.
  3. The page module imports without side effects, exposes
     ``agent_skills_tab``, and ``main.py`` wires the import + Tab.

No Gradio rendering is exercised — that would need a running server. We
inspect the page module's source for the structural invariants the
runtime depends on (versions plumbed with ``entity_type="agent_skill"``).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make ``web_ui.app.*`` importable. The web_ui isn't a packaged
# distribution; the Gradio entry point adjusts sys.path at runtime, so
# the test does the same here.
_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_repo_root / "client" / "python" / "src"))


# ---------------------------------------------------------------------------
# 1. Wrapper methods route to gigaevo_client
# ---------------------------------------------------------------------------


class TestWrapperAgentSkillMethods:
    """``MemoryClientWrapper`` should expose 4 agent_skill methods that
    delegate to the underlying ``GigaEvoClient``."""

    @pytest.fixture
    def wrapper(self):
        from web_ui.app.client import MemoryClientWrapper

        w = MemoryClientWrapper.__new__(MemoryClientWrapper)  # bypass __init__
        w._client = MagicMock()
        return w

    def test_method_names_present(self):
        from web_ui.app.client import MemoryClientWrapper

        for name in (
            "get_agent_skills",
            "get_agent_skill",
            "save_agent_skill",
            "delete_agent_skill",
        ):
            assert hasattr(MemoryClientWrapper, name), name
            assert callable(getattr(MemoryClientWrapper, name)), name

    def test_get_agent_skills_lists_and_converts(self, wrapper):
        entity = MagicMock()
        entity.entity_id = "sk-1"
        entity.entity_type = "agent_skill"
        entity.version_id = "v1"
        entity.channel = "latest"
        entity.etag = "abc"
        entity.meta = {"name": "pdf-extract"}
        entity.content = {"name": "pdf-extract"}
        entity.favourite = False
        entity.run_count = 0
        entity.last_run_at = None
        entity.display_name = None
        entity.description = None
        wrapper._client.list_agent_skills.return_value = [entity]

        result = wrapper.get_agent_skills(limit=25, offset=0)

        wrapper._client.list_agent_skills.assert_called_once_with(limit=25, offset=0)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["entity_id"] == "sk-1"
        # confirm library fields plumb through _entity_to_dict
        assert result[0]["favourite"] is False
        assert result[0]["run_count"] == 0

    def test_get_agent_skill_calls_dict_accessor(self, wrapper):
        wrapper._client.get_agent_skill_dict.return_value = {
            "name": "weather",
            "uri": "github://...",
        }
        result = wrapper.get_agent_skill("sk-2", channel="stable")
        wrapper._client.get_agent_skill_dict.assert_called_once_with(
            "sk-2", channel="stable"
        )
        assert result == {
            "content": {"name": "weather", "uri": "github://..."},
            "entity_id": "sk-2",
        }

    def test_save_agent_skill_forwards_meta_and_content(self, wrapper):
        ref = MagicMock()
        ref.entity_id = "sk-3"
        ref.version_id = "v9"
        wrapper._client.save_agent_skill.return_value = ref

        data = {
            "meta": {
                "name": "presentation-builder",
                "tags": ["pptx", "office"],
                "author": "mage",
                "when_to_use": "When the user asks for slides.",
            },
            "channel": "latest",
            "content": {
                "name": "presentation-builder",
                "description": "Builds PPTX",
                "uri": "github://pptx",
                "sha256": "a" * 64,
                "manifest": {},
                "instructions": "...",
                "allowed_tools": ["Read", "Write"],
                "tags": ["pptx"],
            },
        }

        result = wrapper.save_agent_skill(data)

        kwargs = wrapper._client.save_agent_skill.call_args.kwargs
        assert kwargs["skill"] == data["content"]
        assert kwargs["name"] == "presentation-builder"
        assert kwargs["tags"] == ["pptx", "office"]
        assert kwargs["when_to_use"] == "When the user asks for slides."
        assert kwargs["author"] == "mage"
        assert kwargs["channel"] == "latest"
        assert kwargs["entity_id"] is None
        assert result == {"entity_id": "sk-3", "version_id": "v9"}

    def test_save_agent_skill_passes_entity_id_when_updating(self, wrapper):
        ref = MagicMock()
        ref.entity_id = "sk-4"
        ref.version_id = "v2"
        wrapper._client.save_agent_skill.return_value = ref

        wrapper.save_agent_skill(
            {
                "meta": {"name": "x"},
                "content": {"x": 1},
                "entity_id": "sk-4",
                "channel": "stable",
            }
        )
        kwargs = wrapper._client.save_agent_skill.call_args.kwargs
        assert kwargs["entity_id"] == "sk-4"
        assert kwargs["channel"] == "stable"

    def test_save_agent_skill_defaults_name_and_channel(self, wrapper):
        ref = MagicMock()
        ref.entity_id = "sk-5"
        ref.version_id = "v0"
        wrapper._client.save_agent_skill.return_value = ref

        wrapper.save_agent_skill({"content": {}})

        kwargs = wrapper._client.save_agent_skill.call_args.kwargs
        assert kwargs["name"] == "Unnamed"
        assert kwargs["tags"] == []
        assert kwargs["channel"] == "latest"

    def test_delete_agent_skill_forwards(self, wrapper):
        wrapper._client.delete_agent_skill.return_value = True
        assert wrapper.delete_agent_skill("sk-6") is True
        wrapper._client.delete_agent_skill.assert_called_once_with("sk-6")


# ---------------------------------------------------------------------------
# 2. EntityTypeConfig knows about agent_skills
# ---------------------------------------------------------------------------


class TestEntityTypeConfig:
    def test_agent_skills_entry_present(self):
        from web_ui.app.pages.base import EntityTypeConfig

        cfg = EntityTypeConfig.get("agent_skills")
        assert cfg["name"] == "Agent Skill"
        assert cfg["plural"] == "Agent Skills"
        assert cfg["type"] == "agent_skill"
        # Placeholder advertises the schema so a new user sees the
        # SKILL.md projection shape, not an empty object.
        for required_field in ("name", "uri", "sha256", "allowed_tools"):
            assert required_field in cfg["placeholder"], required_field


# ---------------------------------------------------------------------------
# 3. Page module + main.py wiring
# ---------------------------------------------------------------------------


class TestPageModule:
    """Confirm the page module imports and reflects the agent_skill
    entity-type contract.

    Gradio is a heavy import (Hugging Face etc.); skip if the test
    environment can't satisfy it. The tests below still check the
    module's source where they can — that way the file's invariants
    are protected even when ``gradio`` isn't available locally.
    """

    PAGE_PATH = (
        Path(__file__).resolve().parent.parent / "app" / "pages" / "agent_skills.py"
    )
    MAIN_PATH = Path(__file__).resolve().parent.parent / "app" / "main.py"

    def test_page_file_exists(self):
        assert self.PAGE_PATH.is_file()

    def test_page_versions_use_agent_skill_entity_type(self):
        """The 5 version-helper calls in the page must pass
        ``entity_type="agent_skill"`` so the API hits
        ``/v1/agent-skills/{id}/versions...`` and not the agents path."""
        src = self.PAGE_PATH.read_text()
        # 5 version-flavoured helpers: load_versions_list,
        # load_version_detail, compute_version_diff, revert_entity,
        # pin_channel_version, promote_channel — each must carry the
        # ``"agent_skill"`` arg.
        for helper in (
            "load_versions_list",
            "load_version_detail",
            "compute_version_diff",
            "revert_entity",
            "pin_channel_version",
            "promote_channel",
        ):
            assert f'{helper}(' in src, helper
        # And every one of those calls should reference the singular type.
        assert src.count('"agent_skill"') >= 6

    def test_main_module_imports_and_mounts_tab(self):
        """``main.py`` must import ``agent_skills_tab`` AND wire it as a Tab."""
        src = self.MAIN_PATH.read_text()
        assert "from .pages.agent_skills import agent_skills_tab" in src
        assert "agent_skills_tab(client)" in src
        # The visible label uses the canonical name — important for the
        # CARE TUI users who learn the tab from screenshots.
        assert "Agent Skills" in src

    @pytest.mark.skipif(
        "gradio" not in sys.modules
        and not any(
            (Path(p) / "gradio").exists()
            or (Path(p) / "gradio").with_suffix(".py").exists()
            for p in sys.path
            if p
        ),
        reason="gradio not available in this test environment",
    )
    def test_page_module_imports(self):
        from web_ui.app.pages import agent_skills as page

        assert hasattr(page, "agent_skills_tab")
        assert callable(page.agent_skills_tab)
        # Single positional arg: the client wrapper.
        sig = inspect.signature(page.agent_skills_tab)
        assert list(sig.parameters) == ["client"]
