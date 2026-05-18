"""Tests for agent_skill operations in MemoryClient."""

import hashlib

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient, NotFoundError
from gigaevo_memory.models import AgentSkillSpec, EntityRef


SAMPLE_SHA = hashlib.sha256(b"SKILL.md").hexdigest()


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


@pytest.fixture
def sample_skill_spec():
    return AgentSkillSpec(
        name="pdf",
        description="Extract structured data from PDFs.",
        uri="github://anthropics/skills/skills/pdf@main",
        sha256=SAMPLE_SHA,
        manifest={"name": "pdf", "license": "Apache-2.0"},
        instructions="Use pdfplumber for tables.",
        allowed_tools=["Bash(python:*)", "Read", "Write"],
        tags=["pdf", "extraction"],
        tarball_url="https://codeload.github.com/anthropics/skills/tar.gz/main",
    )


class TestAgentSkillsMixinComposition:
    def test_memory_client_inherits_agent_skill_methods(self, client):
        for name in (
            "get_agent_skill",
            "get_agent_skill_dict",
            "save_agent_skill",
            "list_agent_skills",
            "delete_agent_skill",
        ):
            assert hasattr(client, name), f"MemoryClient missing {name}"

    def test_url_routing_uses_kebab_case(self):
        """`_TYPE_PLURAL` maps agent_skill → agent-skills."""
        from gigaevo_memory._base import _TYPE_PLURAL

        assert _TYPE_PLURAL["agent_skill"] == "agent-skills"


class TestGetAgentSkill:
    def test_get_agent_skill_success(self, client, sample_skill_spec):
        response = {
            "entity_type": "agent_skill",
            "entity_id": "skill-id-123",
            "version_id": "ver-456",
            "channel": "latest",
            "etag": "abc123",
            "meta": {"name": "pdf"},
            "content": sample_skill_spec.model_dump(mode="json"),
        }

        with respx.mock:
            respx.get("http://test-api:8000/v1/agent-skills/skill-id-123").mock(
                return_value=httpx.Response(200, json=response)
            )
            skill = client.get_agent_skill("skill-id-123")

        assert isinstance(skill, AgentSkillSpec)
        assert skill.name == "pdf"
        assert skill.uri == "github://anthropics/skills/skills/pdf@main"
        assert skill.sha256 == SAMPLE_SHA
        assert "Bash(python:*)" in skill.allowed_tools

    def test_get_agent_skill_dict(self, client, sample_skill_spec):
        """`get_agent_skill_dict` returns raw content without typed validation."""
        # Use a payload that wouldn't pass AgentSkillSpec validation to prove
        # the dict accessor bypasses the typed schema.
        raw = {"name": "x", "uri": "local://x"}  # missing required fields
        response = {
            "entity_type": "agent_skill",
            "entity_id": "id",
            "version_id": "ver",
            "channel": "latest",
            "etag": "e",
            "meta": {},
            "content": raw,
        }

        with respx.mock:
            respx.get("http://test-api:8000/v1/agent-skills/id").mock(
                return_value=httpx.Response(200, json=response),
            )
            assert client.get_agent_skill_dict("id") == raw

    def test_get_agent_skill_not_found(self, client):
        with respx.mock:
            respx.get("http://test-api:8000/v1/agent-skills/missing-id").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"})
            )
            with pytest.raises(NotFoundError):
                client.get_agent_skill("missing-id")


class TestSaveAgentSkill:
    def test_save_agent_skill_create(self, client, sample_skill_spec):
        response = {
            "entity_type": "agent_skill",
            "entity_id": "new-skill-id",
            "version_id": "ver-1",
            "channel": "latest",
            "etag": "abc",
            "meta": {"name": "pdf"},
            "content": sample_skill_spec.model_dump(mode="json"),
        }

        with respx.mock:
            respx.post("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(201, json=response)
            )
            ref = client.save_agent_skill(
                sample_skill_spec,
                name="pdf",
                tags=["pdf"],
                when_to_use="Extract text from PDFs",
            )

        assert isinstance(ref, EntityRef)
        assert ref.entity_id == "new-skill-id"
        assert ref.entity_type == "agent_skill"
        assert ref.channel == "latest"

    def test_save_agent_skill_update(self, client, sample_skill_spec):
        response = {
            "entity_type": "agent_skill",
            "entity_id": "existing-skill-id",
            "version_id": "ver-2",
            "channel": "latest",
            "etag": "def",
            "meta": {"name": "pdf"},
            "content": sample_skill_spec.model_dump(mode="json"),
        }

        with respx.mock:
            respx.put("http://test-api:8000/v1/agent-skills/existing-skill-id").mock(
                return_value=httpx.Response(200, json=response)
            )
            ref = client.save_agent_skill(
                sample_skill_spec,
                name="pdf",
                entity_id="existing-skill-id",
            )

        assert ref.entity_id == "existing-skill-id"
        assert ref.version_id == "ver-2"

    def test_save_agent_skill_accepts_dict(self, client):
        """`save_agent_skill` also accepts a raw dict (no typed validation)."""
        raw = {"name": "pdf", "uri": "local:///tmp/pdf", "sha256": SAMPLE_SHA}
        response = {
            "entity_type": "agent_skill",
            "entity_id": "id",
            "version_id": "ver",
            "channel": "latest",
            "etag": "e",
            "meta": {"name": "pdf"},
            "content": raw,
        }

        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(201, json=response)
            )
            ref = client.save_agent_skill(raw, name="pdf")

        assert ref.entity_id == "id"
        # Verify the posted body carried the raw content dict.
        import json

        sent = json.loads(route.calls.last.request.content)
        assert sent["content"] == raw


class TestListAgentSkills:
    def test_list_agent_skills_success(self, client):
        response = [
            {
                "entity_type": "agent_skill",
                "entity_id": "skill-1",
                "version_id": "ver-1",
                "channel": "latest",
                "etag": "abc",
                "meta": {"name": "pdf"},
                "content": {"name": "pdf"},
            },
            {
                "entity_type": "agent_skill",
                "entity_id": "skill-2",
                "version_id": "ver-1",
                "channel": "latest",
                "etag": "def",
                "meta": {"name": "pptx"},
                "content": {"name": "pptx"},
            },
        ]

        with respx.mock:
            respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=response)
            )
            skills = client.list_agent_skills(limit=10)

        assert len(skills) == 2
        assert skills[0].entity_id == "skill-1"
        assert skills[1].entity_id == "skill-2"


class TestDeleteAgentSkill:
    def test_delete_agent_skill_success(self, client):
        with respx.mock:
            respx.delete("http://test-api:8000/v1/agent-skills/skill-id-123").mock(
                return_value=httpx.Response(204)
            )
            assert client.delete_agent_skill("skill-id-123") is True

    def test_delete_agent_skill_not_found(self, client):
        with respx.mock:
            respx.delete("http://test-api:8000/v1/agent-skills/missing-id").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"})
            )
            with pytest.raises(NotFoundError):
                client.delete_agent_skill("missing-id")
