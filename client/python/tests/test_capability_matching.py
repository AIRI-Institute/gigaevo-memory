"""Tests for ``MemoryClient.find_capability_matches`` (§4 P1).

Verifies the helper:
  * Issues the right search call against `agent_skill` entities with
    the `skill_description` document_kind.
  * Optionally runs a second `skill_instructions` query (``deep=True``)
    and merges results, deduped by ``entity_id``, keeping higher scores.
  * Returns top-K `CapabilityHit` objects ranked by score.
  * Handles empty / whitespace queries gracefully.
"""

import json

import httpx
import pytest
import respx

from gigaevo_memory import CapabilityHit, MemoryClient
from gigaevo_memory.search_types import SearchType


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


def _hit(entity_id: str, name: str, score: float, **ov) -> dict:
    base = {
        "entity_id": entity_id,
        "entity_type": "agent_skill",
        "name": name,
        "score": score,
        "channel": "latest",
        "version_id": "v1",
        "tags": [],
        "when_to_use": None,
        "content": {"name": name, "description": f"{name} description"},
        "document_id": "doc-1",
        "document_kind": "skill_description",
        "snippet": f"{name} snippet",
    }
    base.update(ov)
    return base


class TestFindCapabilityMatchesBM25:
    def test_returns_capability_hits_ranked_by_score(self, client):
        with respx.mock:
            respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "hits": [
                            _hit("sk-pdf", "pdf", 0.85),
                            _hit("sk-ocr", "ocr", 0.41),
                            _hit("sk-html", "html2pdf", 0.22),
                        ]
                    },
                )
            )
            results = client.find_capability_matches(
                "extract structured data from a PDF", top_k=3
            )
        assert len(results) == 3
        assert isinstance(results[0], CapabilityHit)
        assert results[0].entity_id == "sk-pdf"
        assert results[0].score == 0.85
        # Hits propagate score order.
        assert [h.score for h in results] == [0.85, 0.41, 0.22]

    def test_sends_skill_description_document_kind(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(200, json={"hits": []})
            )
            client.find_capability_matches("extract PDF text")
        body = json.loads(route.calls.last.request.content)
        assert body["entity_type"] == "agent_skill"
        assert body["document_kind"] == "skill_description"
        assert body["search_type"] == "bm25"

    def test_namespace_forwarded(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(200, json={"hits": []})
            )
            client.find_capability_matches("extract PDF", namespace="glazkov")
        body = json.loads(route.calls.last.request.content)
        assert body["namespace"] == "glazkov"

    def test_top_k_passed_through(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(200, json={"hits": []})
            )
            client.find_capability_matches("X", top_k=7)
        body = json.loads(route.calls.last.request.content)
        assert body["top_k"] == 7


class TestFindCapabilityMatchesEmptyInput:
    def test_empty_query_returns_empty_without_network(self, client):
        """No network round-trip when the query is blank."""
        with respx.mock(assert_all_called=False):
            assert client.find_capability_matches("") == []
            assert client.find_capability_matches("   ") == []


class TestFindCapabilityMatchesProjection:
    def test_description_pulled_from_content(self, client):
        with respx.mock:
            respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(
                    200,
                    json={"hits": [
                        _hit("sk-pdf", "pdf", 0.9,
                             content={"name": "pdf", "description": "Extract structured data from PDFs."}),
                    ]},
                )
            )
            (hit,) = client.find_capability_matches("PDF extraction")
        assert hit.description == "Extract structured data from PDFs."
        assert hit.matched_via == "skill_description"

    def test_matched_via_falls_back_when_document_kind_missing(self, client):
        with respx.mock:
            respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(
                    200,
                    json={"hits": [_hit("sk", "x", 0.5, document_kind=None)]},
                )
            )
            (hit,) = client.find_capability_matches("x")
        # When the server returns no document_kind on the hit,
        # CapabilityHit.from_search_hit uses the supplied fallback.
        assert hit.matched_via == "skill_description"


class TestFindCapabilityMatchesDeep:
    """`deep=True` runs a second query against `skill_instructions`."""

    def test_deep_issues_two_searches(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(200, json={"hits": []})
            )
            client.find_capability_matches("pdfplumber tables", deep=True)
        # Two calls: skill_description and skill_instructions.
        kinds = [
            json.loads(call.request.content)["document_kind"]
            for call in route.calls
        ]
        assert kinds == ["skill_description", "skill_instructions"]

    def test_deep_merges_dedupes_by_entity_id_keeping_higher_score(self, client):
        """When both doc kinds hit the same skill, keep the higher-score hit."""
        with respx.mock:
            # First call: skill_description returns sk-pdf with low score.
            # Second call: skill_instructions returns sk-pdf with high score.
            route = respx.post("http://test-api:8000/v1/search/unified")
            route.side_effect = [
                httpx.Response(200, json={"hits": [
                    _hit("sk-pdf", "pdf", 0.30, document_kind="skill_description"),
                    _hit("sk-ocr", "ocr", 0.20, document_kind="skill_description"),
                ]}),
                httpx.Response(200, json={"hits": [
                    _hit("sk-pdf", "pdf", 0.91, document_kind="skill_instructions"),
                ]}),
            ]
            results = client.find_capability_matches(
                "use pdfplumber for tables", top_k=5, deep=True
            )
        # sk-pdf wins because instruction-match score (0.91) > description (0.30).
        assert results[0].entity_id == "sk-pdf"
        assert results[0].score == 0.91
        assert results[0].matched_via == "skill_instructions"
        # sk-ocr (only in description hits) is preserved.
        assert {h.entity_id for h in results} == {"sk-pdf", "sk-ocr"}

    def test_deep_keeps_description_hit_when_higher(self, client):
        """Inverse case: description score wins, instructions hit ignored."""
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/search/unified")
            route.side_effect = [
                httpx.Response(200, json={"hits": [
                    _hit("sk-pdf", "pdf", 0.85, document_kind="skill_description"),
                ]}),
                httpx.Response(200, json={"hits": [
                    _hit("sk-pdf", "pdf", 0.20, document_kind="skill_instructions"),
                ]}),
            ]
            (hit,) = client.find_capability_matches("X", deep=True)
        assert hit.score == 0.85
        assert hit.matched_via == "skill_description"


class TestVectorAndHybrid:
    """Vector/hybrid paths require an embedding provider but otherwise behave the same."""

    def test_vector_search_passes_query_vector(self, client):
        """Pass an explicit fake provider so vector search runs without a model."""

        class FakeProvider:
            def embed_query(self, query):
                return [0.1, 0.2, 0.3]

            def embed(self, queries):  # pragma: no cover - not exercised here
                return [self.embed_query(q) for q in queries]

        with respx.mock:
            route = respx.post("http://test-api:8000/v1/search/unified").mock(
                return_value=httpx.Response(200, json={"hits": []})
            )
            client.find_capability_matches(
                "extract PDFs",
                search_type=SearchType.VECTOR,
                embedding_provider=FakeProvider(),
            )
        body = json.loads(route.calls.last.request.content)
        assert body["search_type"] == "vector"
        assert body["query_vector"] == [0.1, 0.2, 0.3]
