"""Tests for ``MemoryClient.ingest_skill_from_carl`` (§1.3 P1).

The helper is duck-typed: it accepts a CARL ``ResolvedSkill``-like
object (we mock the shape), an :class:`AgentSkillSpec`, or a dict.
We never import ``mmar_carl`` so the test suite doesn't take on CARL
as a runtime dependency.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient
from gigaevo_memory.agent_skills import _extract_skill_spec
from gigaevo_memory.models import AgentSkillSpec


SHA = hashlib.sha256(b"SKILL.md-pdf-content").hexdigest()


# ---------------------------------------------------------------------------
# Duck-typed CARL ResolvedSkill / SkillManifest stand-ins
# ---------------------------------------------------------------------------


@dataclass
class FakeManifest:
    name: str = "pdf"
    description: str = "Extract structured data from PDFs."
    instructions: str = "Use pdfplumber for tables, pdfminer for text."
    metadata: dict = field(default_factory=lambda: {"license": "Apache-2.0"})
    compatibility: dict | None = None
    _allowed_tools: list[str] = field(
        default_factory=lambda: ["Bash(python:*)", "Read", "Write"]
    )
    _allowed_tools_callable: Callable[[], list[str]] | None = None

    def get_allowed_tools(self) -> list[str]:
        if self._allowed_tools_callable is not None:
            return self._allowed_tools_callable()
        return list(self._allowed_tools)


@dataclass
class FakeResolvedSkill:
    manifest: Any = field(default_factory=FakeManifest)
    sha256: str = SHA
    source_uri: str = "github://anthropics/skills/skills/pdf@main"
    tarball_url: str | None = "https://codeload.github.com/anthropics/skills/tar.gz/main"
    tarball_sha256: str | None = None


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


# ---------------------------------------------------------------------------
# _extract_skill_spec — pure projection
# ---------------------------------------------------------------------------


class TestExtractFromCarlResolvedSkill:
    def test_full_round_trip(self):
        spec = _extract_skill_spec(FakeResolvedSkill())
        assert isinstance(spec, AgentSkillSpec)
        assert spec.name == "pdf"
        assert spec.description == "Extract structured data from PDFs."
        assert spec.uri == "github://anthropics/skills/skills/pdf@main"
        assert spec.sha256 == SHA
        assert spec.allowed_tools == ["Bash(python:*)", "Read", "Write"]
        assert spec.manifest == {"license": "Apache-2.0"}
        assert "pdfplumber" in spec.instructions

    def test_falls_back_to_uri_when_source_uri_missing(self):
        @dataclass
        class _Resolved:
            manifest: Any = field(default_factory=FakeManifest)
            sha256: str = SHA
            uri: str = "local:///tmp/skill"

        spec = _extract_skill_spec(_Resolved())
        assert spec.uri == "local:///tmp/skill"

    def test_falls_back_to_skill_md_sha256(self):
        @dataclass
        class _Resolved:
            manifest: Any = field(default_factory=FakeManifest)
            skill_md_sha256: str = SHA
            source_uri: str = "local:///tmp/skill"

        spec = _extract_skill_spec(_Resolved())
        assert spec.sha256 == SHA

    def test_raises_without_sha(self):
        @dataclass
        class _Resolved:
            manifest: Any = field(default_factory=FakeManifest)
            source_uri: str = "x"

        with pytest.raises(ValueError, match="sha256"):
            _extract_skill_spec(_Resolved())

    def test_raises_without_uri(self):
        @dataclass
        class _Resolved:
            manifest: Any = field(default_factory=FakeManifest)
            sha256: str = SHA

        with pytest.raises(ValueError, match="source_uri"):
            _extract_skill_spec(_Resolved())

    def test_raises_without_manifest(self):
        class _NoManifest:
            sha256 = SHA
            source_uri = "x"

        with pytest.raises(ValueError, match="manifest"):
            _extract_skill_spec(_NoManifest())

    def test_uses_get_allowed_tools_method_first(self):
        manifest = FakeManifest(_allowed_tools_callable=lambda: ["Bash(git:*)"])
        spec = _extract_skill_spec(FakeResolvedSkill(manifest=manifest))
        assert spec.allowed_tools == ["Bash(git:*)"]

    def test_falls_back_to_allowed_tools_attr_when_no_method(self):
        class _Manifest:
            name = "x"
            description = "x"
            instructions = "x"
            metadata: dict = {}
            compatibility = None
            allowed_tools = ["Read"]

        spec = _extract_skill_spec(FakeResolvedSkill(manifest=_Manifest()))
        assert spec.allowed_tools == ["Read"]

    def test_extracts_tags_from_manifest_attr(self):
        class _Manifest(FakeManifest):
            tags: list[str] = ["pdf", "extraction"]

        spec = _extract_skill_spec(FakeResolvedSkill(manifest=_Manifest()))
        assert spec.tags == ["pdf", "extraction"]

    def test_extracts_tags_from_metadata_when_attr_missing(self):
        manifest = FakeManifest(metadata={"tags": ["a", "b"], "license": "MIT"})
        spec = _extract_skill_spec(FakeResolvedSkill(manifest=manifest))
        assert spec.tags == ["a", "b"]

    def test_passes_through_agent_skill_spec(self):
        original = AgentSkillSpec(
            name="x", description="d", uri="local:///x", sha256=SHA
        )
        assert _extract_skill_spec(original) is original

    def test_accepts_dict_input(self):
        data = {"name": "x", "description": "d", "uri": "local:///x", "sha256": SHA}
        spec = _extract_skill_spec(data)
        assert spec.name == "x"

    def test_propagates_tarball_url(self):
        spec = _extract_skill_spec(FakeResolvedSkill())
        assert spec.tarball_url == "https://codeload.github.com/anthropics/skills/tar.gz/main"


# ---------------------------------------------------------------------------
# ingest_skill_from_carl — HTTP wiring
# ---------------------------------------------------------------------------


def _agent_skill_response_payload() -> dict:
    return {
        "entity_type": "agent_skill",
        "entity_id": "sk-pdf-001",
        "version_id": "v1",
        "channel": "latest",
        "etag": "etag-1",
        "meta": {"name": "pdf", "tags": ["pdf"]},
        "content": {"name": "pdf"},
        "favourite": False,
        "run_count": 0,
        "last_run_at": None,
        "display_name": "pdf",
        "description": "Extract structured data from PDFs.",
    }


class TestIngestSkillFromCarlHttp:
    def test_create_path_no_entity_id(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(201, json=_agent_skill_response_payload())
            )
            ref = client.ingest_skill_from_carl(FakeResolvedSkill())

        assert ref.entity_id == "sk-pdf-001"
        assert ref.entity_type == "agent_skill"
        body = json.loads(route.calls.last.request.content)
        assert body["meta"]["name"] == "pdf"
        assert body["content"]["uri"] == "github://anthropics/skills/skills/pdf@main"
        assert body["content"]["sha256"] == SHA
        assert "Bash(python:*)" in body["content"]["allowed_tools"]

    def test_update_path_with_entity_id(self, client):
        with respx.mock:
            route = respx.put("http://test-api:8000/v1/agent-skills/sk-existing").mock(
                return_value=httpx.Response(200, json=_agent_skill_response_payload())
            )
            ref = client.ingest_skill_from_carl(
                FakeResolvedSkill(),
                entity_id="sk-existing",
            )
        # The router returned the canned ID; the call itself targeted "sk-existing".
        assert route.called
        assert "sk-existing" in str(route.calls.last.request.url)
        assert ref.entity_id == "sk-pdf-001"

    def test_override_name_and_tags(self, client):
        """Caller can override the auto-extracted name / tags."""
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(201, json=_agent_skill_response_payload())
            )
            client.ingest_skill_from_carl(
                FakeResolvedSkill(),
                name="pdf-overridden",
                tags=["custom", "tag"],
                namespace="glazkov",
                author="mage",
            )
        body = json.loads(route.calls.last.request.content)
        assert body["meta"]["name"] == "pdf-overridden"
        assert body["meta"]["tags"] == ["custom", "tag"]
        assert body["meta"]["namespace"] == "glazkov"
        assert body["meta"]["author"] == "mage"

    def test_accepts_agent_skill_spec_directly(self, client):
        spec = AgentSkillSpec(
            name="pre-built",
            description="d",
            uri="local:///x",
            sha256=SHA,
            allowed_tools=["Read"],
        )
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(201, json=_agent_skill_response_payload())
            )
            client.ingest_skill_from_carl(spec)
        body = json.loads(route.calls.last.request.content)
        assert body["content"]["name"] == "pre-built"
        assert body["content"]["allowed_tools"] == ["Read"]

    def test_accepts_dict_input(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(201, json=_agent_skill_response_payload())
            )
            client.ingest_skill_from_carl({
                "name": "x", "description": "d", "uri": "local:///x",
                "sha256": SHA,
            })
        body = json.loads(route.calls.last.request.content)
        assert body["content"]["uri"] == "local:///x"

    def test_missing_sha_raises_before_network(self, client):
        """Validation happens before the HTTP round-trip."""
        @dataclass
        class _Bad:
            manifest: Any = field(default_factory=FakeManifest)
            source_uri: str = "x"

        with respx.mock(assert_all_called=False) as mock:
            mock.post("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(201, json={})  # would fail if reached
            )
            with pytest.raises(ValueError, match="sha256"):
                client.ingest_skill_from_carl(_Bad())
            # No HTTP call.
            assert len(mock.calls) == 0
