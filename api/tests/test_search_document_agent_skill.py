"""Unit tests for AgentSkill search-document derivation.

These cover the pure ``derive_agent_skill_search_documents`` function
and the dispatch logic in ``sync_entity_search_documents`` (without
hitting the database — the dispatch test only checks the routing).
"""

import hashlib

import pytest

from app.services.search_document_service import (
    DOCUMENT_KIND_FULL_CARD,
    DOCUMENT_KIND_SKILL_ALLOWED_TOOLS,
    DOCUMENT_KIND_SKILL_DESCRIPTION,
    DOCUMENT_KIND_SKILL_FULL,
    DOCUMENT_KIND_SKILL_INSTRUCTIONS,
    DOCUMENT_KINDS,
    INDEXED_ENTITY_TYPES,
    default_bm25_document_kind,
    default_vector_document_kind,
    derive_agent_skill_search_documents,
)


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.fixture
def pdf_skill_content() -> dict:
    return {
        "name": "pdf",
        "description": "Extract structured data from PDFs.",
        "uri": "github://anthropics/skills/skills/pdf@main",
        "sha256": _sha256("SKILL.md"),
        "manifest": {"name": "pdf", "license": "Apache-2.0"},
        "instructions": (
            "# PDF skill\n\n"
            "Use pdfplumber to read tables and pdfminer for plain text.\n"
            "Always write outputs to /workspace/out/."
        ),
        "allowed_tools": [
            "Bash(python:*)",
            "Read",
            "Write",
            "WebFetch(domain:api.unpdf.com)",
        ],
        "tags": ["pdf", "extraction"],
    }


class TestDeriveAgentSkillDocs:
    """Pure derivation: input dict → list of DerivedSearchDocument."""

    def test_full_skill_produces_four_doc_kinds(self, pdf_skill_content):
        docs = derive_agent_skill_search_documents(pdf_skill_content)
        kinds = {d.document_kind for d in docs}
        assert kinds == {
            DOCUMENT_KIND_SKILL_DESCRIPTION,
            DOCUMENT_KIND_SKILL_INSTRUCTIONS,
            DOCUMENT_KIND_SKILL_FULL,
            DOCUMENT_KIND_SKILL_ALLOWED_TOOLS,
        }

    def test_description_doc_combines_name_and_description(self, pdf_skill_content):
        docs = {d.document_kind: d for d in derive_agent_skill_search_documents(pdf_skill_content)}
        text = docs[DOCUMENT_KIND_SKILL_DESCRIPTION].text_content
        assert "pdf" in text
        assert "Extract structured data from PDFs." in text

    def test_instructions_doc_carries_skill_md_body(self, pdf_skill_content):
        docs = {d.document_kind: d for d in derive_agent_skill_search_documents(pdf_skill_content)}
        body = docs[DOCUMENT_KIND_SKILL_INSTRUCTIONS].text_content
        assert "pdfplumber" in body
        assert "/workspace/out/" in body

    def test_full_doc_concatenates_three_sources(self, pdf_skill_content):
        docs = {d.document_kind: d for d in derive_agent_skill_search_documents(pdf_skill_content)}
        full = docs[DOCUMENT_KIND_SKILL_FULL].text_content
        assert "pdf" in full
        assert "Extract structured data from PDFs." in full
        assert "pdfplumber" in full

    def test_allowed_tools_doc_serialises_as_csv(self, pdf_skill_content):
        docs = {d.document_kind: d for d in derive_agent_skill_search_documents(pdf_skill_content)}
        tokens = docs[DOCUMENT_KIND_SKILL_ALLOWED_TOOLS].text_content
        # `_stringify` joins lists with ", " — let's match precisely.
        assert "Bash(python:*)" in tokens
        assert "Read" in tokens
        assert "WebFetch(domain:api.unpdf.com)" in tokens

    def test_card_id_uses_skill_name_as_external_id(self, pdf_skill_content):
        docs = derive_agent_skill_search_documents(pdf_skill_content)
        for d in docs:
            assert d.card_id == "pdf"

    def test_meta_json_carries_skill_name_and_uri(self, pdf_skill_content):
        docs = derive_agent_skill_search_documents(pdf_skill_content)
        for d in docs:
            assert d.meta_json["skill_name"] == "pdf"
            assert d.meta_json["uri"] == "github://anthropics/skills/skills/pdf@main"
            assert d.meta_json["document_kind"] == d.document_kind

    def test_empty_content_returns_empty_list(self):
        assert derive_agent_skill_search_documents({}) == []

    def test_non_dict_content_returns_empty_list(self):
        assert derive_agent_skill_search_documents(None) == []  # type: ignore[arg-type]
        assert derive_agent_skill_search_documents("string") == []  # type: ignore[arg-type]

    def test_falls_back_to_uri_when_name_missing(self):
        docs = derive_agent_skill_search_documents(
            {
                "uri": "local:///tmp/skill",
                "description": "Local",
                "instructions": "body",
                "allowed_tools": [],
            }
        )
        # No name → external_id falls back to uri.
        assert all(d.card_id == "local:///tmp/skill" for d in docs)

    def test_partial_content_emits_only_non_empty_kinds(self):
        """Skill with no instructions and no allowed_tools omits those kinds."""
        docs = derive_agent_skill_search_documents(
            {"name": "x", "description": "minimal", "uri": "local:///x"}
        )
        kinds = {d.document_kind for d in docs}
        # description doc present; instructions and allowed_tools doc skipped.
        assert DOCUMENT_KIND_SKILL_DESCRIPTION in kinds
        assert DOCUMENT_KIND_SKILL_INSTRUCTIONS not in kinds
        assert DOCUMENT_KIND_SKILL_ALLOWED_TOOLS not in kinds
        # `skill_full` still emits because name + description are non-empty.
        assert DOCUMENT_KIND_SKILL_FULL in kinds


class TestIndexedEntityTypesConstant:
    """The dispatch allowlist correctly enumerates indexed entity types."""

    def test_indexed_entity_types_contains_memory_card_and_agent_skill(self):
        assert INDEXED_ENTITY_TYPES == {"memory_card", "agent_skill"}

    def test_skill_kinds_registered_in_document_kinds(self):
        for kind in (
            DOCUMENT_KIND_SKILL_FULL,
            DOCUMENT_KIND_SKILL_DESCRIPTION,
            DOCUMENT_KIND_SKILL_INSTRUCTIONS,
            DOCUMENT_KIND_SKILL_ALLOWED_TOOLS,
        ):
            assert kind in DOCUMENT_KINDS


class TestDefaultDocumentKinds:
    def test_bm25_defaults_cover_indexed_types(self):
        assert default_bm25_document_kind("memory_card") == DOCUMENT_KIND_FULL_CARD
        assert default_bm25_document_kind("agent_skill") == DOCUMENT_KIND_SKILL_FULL

    def test_vector_defaults_cover_indexed_types(self):
        assert default_vector_document_kind("memory_card") == DOCUMENT_KIND_FULL_CARD
        assert (
            default_vector_document_kind("agent_skill")
            == DOCUMENT_KIND_SKILL_INSTRUCTIONS
        )

    def test_non_indexed_types_have_no_default_document_kind(self):
        for entity_type in ("chain", "agent", "step", "unknown"):
            assert default_bm25_document_kind(entity_type) is None
            assert default_vector_document_kind(entity_type) is None


class TestSyncDispatch:
    """`sync_entity_search_documents` routes by entity_type."""

    @pytest.mark.asyncio
    async def test_unknown_entity_type_short_circuits(self, monkeypatch):
        """Entities not in INDEXED_ENTITY_TYPES return after the delete pass."""
        from unittest.mock import AsyncMock, MagicMock

        from app.services import search_document_service as svc

        # Patch out the embedding service so it doesn't try to talk to a real provider.
        derive_calls: list[str] = []

        def _spy_card(content):  # pragma: no cover - should not be called
            derive_calls.append("memory_card")
            return []

        def _spy_skill(content):  # pragma: no cover - should not be called
            derive_calls.append("agent_skill")
            return []

        monkeypatch.setattr(svc, "derive_memory_card_search_documents", _spy_card)
        monkeypatch.setattr(svc, "derive_agent_skill_search_documents", _spy_skill)

        db = AsyncMock()
        entity = MagicMock(entity_type="chain", entity_id="id", namespace=None)
        version = MagicMock(version_id="v", content_json={})

        await svc.sync_entity_search_documents(db, entity, version)

        # Only the cleanup delete should have run; no derivation.
        assert derive_calls == []
        # And the delete pass was executed at least once.
        assert db.execute.await_count >= 1

    @pytest.mark.asyncio
    async def test_agent_skill_routes_to_skill_derivation(self, monkeypatch):
        """An agent_skill entity dispatches to derive_agent_skill_search_documents."""
        from unittest.mock import AsyncMock, MagicMock

        from app.services import search_document_service as svc

        called: list[str] = []

        def _spy_skill(content):
            called.append("agent_skill")
            return []  # empty → exits before flush/embedding path

        monkeypatch.setattr(svc, "derive_agent_skill_search_documents", _spy_skill)

        db = AsyncMock()
        entity = MagicMock(entity_type="agent_skill", entity_id="id", namespace=None)
        version = MagicMock(version_id="v", content_json={"name": "pdf"})

        await svc.sync_entity_search_documents(db, entity, version)
        assert called == ["agent_skill"]
