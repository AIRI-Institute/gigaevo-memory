"""Tests for ``GigaEvoClient.find_duplicates`` (TODO §4 P3).

Mocks the HTTP boundary via respx; exercises URL composition,
query-param shape, and response parsing into the typed model.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from gigaevo_client import (
    DuplicateMember,
    DuplicatePair,
    DuplicatesResponse,
    GigaEvoClient,
)


SAMPLE_RESPONSE = {
    "entity_type": "chain",
    "channel": "latest",
    "threshold": 0.95,
    "pairs": [
        {
            "entity_a": {
                "entity_id": "11111111-1111-1111-1111-111111111111",
                "version_id": "v-a",
                "name": "fin-triage-v1",
                "display_name": "Finance Triage",
                "namespace": "alice",
            },
            "entity_b": {
                "entity_id": "22222222-2222-2222-2222-222222222222",
                "version_id": "v-b",
                "name": "fin-triage-v2",
                "display_name": "Finance Triage (revised)",
                "namespace": "alice",
            },
            "similarity": 0.987,
            "suggestion": "merge",
        },
    ],
}


@pytest.fixture
def client():
    c = GigaEvoClient(base_url="http://test")
    yield c
    c.close()


class TestRequestShape:
    @respx.mock
    def test_default_params(self, client):
        route = respx.get("http://test/v1/chains/duplicates").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE),
        )
        result = client.find_duplicates("chains")
        assert route.called
        params = dict(route.calls.last.request.url.params)
        assert params == {
            "channel": "latest",
            "threshold": "0.95",
            "limit": "50",
        }
        assert isinstance(result, DuplicatesResponse)

    @respx.mock
    def test_explicit_overrides(self, client):
        route = respx.get("http://test/v1/agent-skills/duplicates").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE),
        )
        client.find_duplicates(
            "agent-skills",
            channel="stable",
            threshold=0.87,
            namespace="alice",
            limit=10,
        )
        params = dict(route.calls.last.request.url.params)
        assert params == {
            "channel": "stable",
            "threshold": "0.87",
            "namespace": "alice",
            "limit": "10",
        }

    @respx.mock
    def test_namespace_omitted_not_sent(self, client):
        """When `namespace=None`, the param must not appear at all —
        the server's default is "scan everything" and we don't want to
        send the literal string "None"."""
        route = respx.get("http://test/v1/chains/duplicates").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE),
        )
        client.find_duplicates("chains")
        params = dict(route.calls.last.request.url.params)
        assert "namespace" not in params


class TestResponseParsing:
    @respx.mock
    def test_typed_round_trip(self, client):
        respx.get("http://test/v1/chains/duplicates").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE),
        )
        result = client.find_duplicates("chains")
        assert isinstance(result, DuplicatesResponse)
        assert result.entity_type == "chain"
        assert result.threshold == 0.95
        assert len(result.pairs) == 1
        pair = result.pairs[0]
        assert isinstance(pair, DuplicatePair)
        assert isinstance(pair.entity_a, DuplicateMember)
        assert pair.entity_a.display_name == "Finance Triage"
        assert pair.entity_b.namespace == "alice"
        assert pair.similarity == 0.987

    @respx.mock
    def test_empty_pairs_round_trip(self, client):
        respx.get("http://test/v1/chains/duplicates").mock(
            return_value=httpx.Response(200, json={
                **SAMPLE_RESPONSE, "pairs": [],
            }),
        )
        result = client.find_duplicates("chains")
        assert result.pairs == []
