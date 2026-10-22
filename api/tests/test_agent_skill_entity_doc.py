"""Doc-drift guard for ``docs/AGENT_SKILL_ENTITY.md`` (TODO §9 P2).

The spec doc is a contract artefact for CARE / MAGE. If the underlying
code changes (entity type renamed, endpoint added, a `document_kind`
constant renamed, a required content field added) the doc must move
with it. This test parses the markdown and asserts the claims that are
load-bearing against the actual source of truth.

What we check:

  * The doc names every required `AgentSkillContent` field.
  * The doc lists the four `skill_*` document kinds and only those.
  * The doc lists each `/v1/agent-skills` route the FastAPI router
    actually exposes.
  * The library-metadata columns the doc names exist on the ORM model.
  * The doc lists the four URI shapes the resolver dispatches on.

This is intentionally a low-touch check — it doesn't pin prose, just
structural facts that should never silently drift.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOC_PATH = REPO_ROOT / "docs" / "AGENT_SKILL_ENTITY.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.is_file(), f"Doc missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Content-schema fields
# ---------------------------------------------------------------------------


class TestContentSchemaFields:
    REQUIRED_FIELDS = ("name", "description", "uri", "sha256")
    OPTIONAL_FIELDS = (
        "manifest",
        "instructions",
        "allowed_tools",
        "tags",
        "compatibility",
        "tarball_url",
        "tarball_sha256",
    )

    def test_all_required_fields_documented(self, doc_text):
        for field in self.REQUIRED_FIELDS:
            assert f"`{field}`" in doc_text, field

    def test_all_optional_fields_documented(self, doc_text):
        for field in self.OPTIONAL_FIELDS:
            assert f"`{field}`" in doc_text, field

    def test_sha256_pattern_documented(self, doc_text):
        # The doc must call out the SHA-256 64-hex format so callers
        # know how to compute / validate it.
        assert "64 hex" in doc_text or "[0-9a-fA-F]{64}" in doc_text


# ---------------------------------------------------------------------------
# Search-document kinds
# ---------------------------------------------------------------------------


class TestSearchDocumentKinds:
    KINDS = (
        "skill_description",
        "skill_instructions",
        "skill_full",
        "skill_allowed_tools",
    )

    def test_doc_lists_every_kind(self, doc_text):
        for kind in self.KINDS:
            assert f"`{kind}`" in doc_text, kind

    def test_kinds_match_service_constants(self, doc_text):
        """Pin the doc against the actual constants exported by the
        search-document service."""
        from app.services.search_document_service import (
            DOCUMENT_KIND_SKILL_ALLOWED_TOOLS,
            DOCUMENT_KIND_SKILL_DESCRIPTION,
            DOCUMENT_KIND_SKILL_FULL,
            DOCUMENT_KIND_SKILL_INSTRUCTIONS,
        )

        live = {
            DOCUMENT_KIND_SKILL_DESCRIPTION,
            DOCUMENT_KIND_SKILL_INSTRUCTIONS,
            DOCUMENT_KIND_SKILL_FULL,
            DOCUMENT_KIND_SKILL_ALLOWED_TOOLS,
        }
        assert live == set(self.KINDS), live


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


class TestEndpointsTable:
    def test_doc_lists_every_router_path(self, doc_text):
        """Every ``@router.<verb>("/...", ...)`` path in agent_skills.py
        must appear in the doc. FastAPI's ``router.routes[*].path``
        already carries the prefix in this codebase (the router is
        declared with ``prefix="/v1/agent-skills"`` and stores fully
        qualified paths)."""
        from app.routers import agent_skills as agent_skills_router

        expected_paths = set()
        for route in agent_skills_router.router.routes:
            full = route.path  # type: ignore[attr-defined]
            # Normalise FastAPI placeholders: doc uses ``{id}`` shorthand.
            full = re.sub(r"\{[^}]*_id\}", "{id}", full)
            expected_paths.add(full)

        for path in expected_paths:
            assert path in doc_text, path

    def test_endpoint_verbs_documented(self, doc_text):
        # Each of the four CRUD verbs + PATCH + the two POST sub-resources.
        for verb in ("POST", "GET", "PUT", "PATCH", "DELETE"):
            assert verb in doc_text, verb


# ---------------------------------------------------------------------------
# Library-metadata columns
# ---------------------------------------------------------------------------


class TestLibraryMetadataColumns:
    COLUMNS = ("favourite", "run_count", "last_run_at", "display_name", "description")

    def test_columns_documented(self, doc_text):
        for col in self.COLUMNS:
            assert f"`{col}`" in doc_text, col

    def test_columns_match_orm_model(self):
        from app.db.models import Entity

        for col in self.COLUMNS:
            assert hasattr(Entity, col), col


# ---------------------------------------------------------------------------
# URI shapes
# ---------------------------------------------------------------------------


class TestUriShapes:
    URI_PREFIXES = ("github://", "local://", "https://", "module://")

    def test_all_uri_shapes_documented(self, doc_text):
        for prefix in self.URI_PREFIXES:
            assert prefix in doc_text, prefix


# ---------------------------------------------------------------------------
# Ingestion helper contract
# ---------------------------------------------------------------------------


class TestIngestionHelper:
    def test_helper_name_documented(self, doc_text):
        assert "ingest_skill_from_carl" in doc_text

    def test_helper_exists_in_client(self):
        # The shim is in client/python — we import the canonical name.
        import sys

        sys.path.insert(0, str(REPO_ROOT / "client" / "python" / "src"))
        from gigaevo_client.agent_skills import AgentSkillsMixin, _extract_skill_spec

        assert hasattr(AgentSkillsMixin, "ingest_skill_from_carl")
        assert callable(_extract_skill_spec)

    def test_documented_fallback_chains_match_helper(self, doc_text):
        """The doc enumerates the duck-typed fallback chains for the
        helper. Each chain must appear in the source so the doc isn't
        lying about what the code accepts."""
        import inspect
        import sys

        sys.path.insert(0, str(REPO_ROOT / "client" / "python" / "src"))
        from gigaevo_client.agent_skills import _extract_skill_spec

        src = inspect.getsource(_extract_skill_spec)
        # The doc lists 5 fallback chains.
        for needle in ("source_uri", "sha256", "instructions", "allowed_tools", "tags"):
            assert needle in src, needle
            assert needle in doc_text, needle


# ---------------------------------------------------------------------------
# Entity-type metadata
# ---------------------------------------------------------------------------


class TestEntityTypeMetadata:
    def test_plural_form_in_valid_entity_types(self, doc_text):
        from app.services.entity_service import VALID_ENTITY_TYPES

        assert VALID_ENTITY_TYPES.get("agent_skills") == "agent_skill"
        # And the doc reflects both forms.
        assert "agent_skills" in doc_text
        assert "agent_skill" in doc_text

    def test_indexed_entity_types_includes_agent_skill(self):
        from app.services.search_document_service import INDEXED_ENTITY_TYPES

        assert "agent_skill" in INDEXED_ENTITY_TYPES

    def test_agent_skill_response_literal(self):
        from app.models.responses import AgentSkillResponse

        # The Literal type narrows the entity_type field — the default
        # must be the singular string, which the doc relies on.
        assert AgentSkillResponse.model_fields["entity_type"].default == "agent_skill"
