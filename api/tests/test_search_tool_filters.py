"""Tests for allowed_tools filters on unified search requests."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.services.search_strategies.base import SearchRequest, SearchType


class TestSearchToolFilterValidation:
    def test_unified_search_rejects_tool_filters_for_non_agent_skill(self):
        response = TestClient(app).post(
            "/v1/search/unified",
            json={
                "search_type": "bm25",
                "query": "test query",
                "top_k": 10,
                "entity_type": "memory_card",
                "requires_tool": ["Read"],
            },
        )

        assert response.status_code == 422

    def test_unified_search_rejects_empty_tool_filters_for_non_agent_skill(self):
        response = TestClient(app).post(
            "/v1/search/unified",
            json={
                "search_type": "bm25",
                "query": "test query",
                "top_k": 10,
                "entity_type": "memory_card",
                "requires_tool": [],
            },
        )

        assert response.status_code == 422

    def test_batch_search_rejects_tool_filters_for_non_agent_skill(self):
        response = TestClient(app).post(
            "/v1/search/batch",
            json={
                "search_type": "bm25",
                "queries": ["query1", "query2"],
                "top_k": 5,
                "entity_type": "memory_card",
                "excludes_tool": ["Bash(python:*)"],
            },
        )

        assert response.status_code == 422

    def test_batch_search_rejects_empty_tool_filters_for_non_agent_skill(self):
        response = TestClient(app).post(
            "/v1/search/batch",
            json={
                "search_type": "bm25",
                "queries": ["query1", "query2"],
                "top_k": 5,
                "entity_type": "memory_card",
                "excludes_tool": [],
            },
        )

        assert response.status_code == 422

    def test_batch_search_rejects_query_vector_count_mismatch(self):
        response = TestClient(app).post(
            "/v1/search/batch",
            json={
                "search_type": "vector",
                "queries": ["query1", "query2"],
                "query_vectors": [[0.1, 0.2, 0.3]],
                "top_k": 5,
                "entity_type": "agent_skill",
            },
        )

        assert response.status_code == 422

    def test_internal_search_request_rejects_empty_filters_for_non_agent_skill(self):
        with pytest.raises(ValidationError):
            SearchRequest(
                search_type=SearchType.BM25,
                query="test query",
                entity_type="memory_card",
                requires_tool=[],
            )
