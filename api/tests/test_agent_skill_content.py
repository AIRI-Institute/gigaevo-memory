"""Tests for the AgentSkillContent request-body schema.

`AgentSkillContent` documents the agreed payload shape CARE/MAGE write
into the `content` field of an `EntityCreateRequest` when posting to
`/v1/agent-skills`. The Memory backend stores `content` as opaque JSON,
so these tests focus on the schema's validation contract and the OpenAPI
component it produces.
"""

import hashlib

import pytest
from pydantic import ValidationError

from app.models.requests import AgentSkillContent


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


SAMPLE_SHA = _sha256("---\nname: pdf\n---\nbody")


class TestAgentSkillContentValidation:
    """Field-level validation contract."""

    def test_minimal_valid_payload(self):
        """The four required fields suffice; defaults fill the rest."""
        c = AgentSkillContent(
            name="pdf",
            description="Extract text from PDFs.",
            uri="github://anthropics/skills/skills/pdf@main",
            sha256=SAMPLE_SHA,
        )
        assert c.name == "pdf"
        assert c.manifest == {}
        assert c.instructions == ""
        assert c.allowed_tools == []
        assert c.tags == []
        assert c.compatibility is None
        assert c.tarball_url is None
        assert c.tarball_sha256 is None

    def test_full_payload_round_trip(self):
        """Every documented field can be set and round-trips via model_dump."""
        payload = {
            "name": "pdf",
            "description": "Extract text from PDFs.",
            "uri": "github://anthropics/skills/skills/pdf@main",
            "sha256": SAMPLE_SHA,
            "manifest": {"name": "pdf", "license": "MIT"},
            "instructions": "## How to use\nRun `python extract.py`.",
            "allowed_tools": [
                "Bash(python:*)",
                "Read",
                "Write",
                "WebFetch(domain:example.com)",
            ],
            "tags": ["pdf", "extraction"],
            "compatibility": {"python": ">=3.10"},
            "tarball_url": "https://codeload.github.com/anthropics/skills/tar.gz/main",
            "tarball_sha256": _sha256("tarball"),
        }
        c = AgentSkillContent(**payload)
        assert c.model_dump() == payload

    def test_name_must_be_non_empty(self):
        with pytest.raises(ValidationError):
            AgentSkillContent(
                name="",
                description="x",
                uri="local:///tmp/skill",
                sha256=SAMPLE_SHA,
            )

    def test_name_max_length(self):
        with pytest.raises(ValidationError):
            AgentSkillContent(
                name="x" * 201,
                description="x",
                uri="local:///tmp/skill",
                sha256=SAMPLE_SHA,
            )

    def test_sha256_must_be_hex_64_chars(self):
        # Wrong length.
        with pytest.raises(ValidationError):
            AgentSkillContent(
                name="x",
                description="x",
                uri="local:///tmp/skill",
                sha256="abc123",
            )
        # Non-hex chars.
        with pytest.raises(ValidationError):
            AgentSkillContent(
                name="x",
                description="x",
                uri="local:///tmp/skill",
                sha256="z" * 64,
            )

    def test_sha256_accepts_uppercase_hex(self):
        c = AgentSkillContent(
            name="x",
            description="x",
            uri="local:///tmp/skill",
            sha256=SAMPLE_SHA.upper(),
        )
        assert c.sha256 == SAMPLE_SHA.upper()

    def test_required_fields_missing(self):
        with pytest.raises(ValidationError) as exc:
            AgentSkillContent(name="x", description="x", uri="local:///tmp/skill")  # no sha256
        # Pydantic reports the missing field by name.
        assert "sha256" in str(exc.value)


class TestAgentSkillContentOpenAPI:
    """Schema reaches the OpenAPI surface CARE clients consume."""

    def test_schema_lists_required_fields(self):
        schema = AgentSkillContent.model_json_schema()
        assert set(schema["required"]) == {"name", "description", "uri", "sha256"}

    def test_schema_documents_allowed_tools_example(self):
        schema = AgentSkillContent.model_json_schema()
        assert "allowed_tools" in schema["properties"]
        assert schema["properties"]["allowed_tools"]["type"] == "array"

    def test_schema_pins_sha256_pattern(self):
        schema = AgentSkillContent.model_json_schema()
        sha = schema["properties"]["sha256"]
        assert sha.get("pattern") == r"^[0-9a-fA-F]{64}$"
        assert sha.get("minLength") == 64
        assert sha.get("maxLength") == 64

    def test_schema_validates_embedded_in_entity_create_payload(self):
        """The agreed shape validates as the `content` field of an EntityCreateRequest.

        CARE's real flow is: build an `AgentSkillContent`, dump it,
        embed the dict in `EntityCreateRequest.content`, POST to
        `/v1/agent-skills`. This test exercises that exact path.
        """
        from app.models.requests import EntityCreateRequest, EntityMeta

        skill = AgentSkillContent(
            name="pdf",
            description="Extract text from PDFs.",
            uri="github://anthropics/skills/skills/pdf@main",
            sha256=SAMPLE_SHA,
            allowed_tools=["Bash(python:*)", "Read"],
            tags=["pdf"],
        )
        req = EntityCreateRequest(
            meta=EntityMeta(
                name="pdf",
                tags=["pdf"],
                when_to_use="Use for PDF extraction",
            ),
            content=skill.model_dump(),
        )
        # Round-trip back to the typed schema preserves every field.
        round_tripped = AgentSkillContent.model_validate(req.content)
        assert round_tripped == skill

    def test_schema_optional_tarball_fields(self):
        """tarball_url / tarball_sha256 are optional, defaulting to None."""
        schema = AgentSkillContent.model_json_schema()
        assert "tarball_url" not in schema["required"]
        assert "tarball_sha256" not in schema["required"]
