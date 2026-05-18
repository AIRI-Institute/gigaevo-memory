"""Tests for ``GigaEvoClient.list_chain_versions_beating`` (TODO §5 P3).

Uses ``respx`` to mock the HTTP boundary; the client is exercised
end-to-end (URL composition, query-param shape, response parsing into
the typed ``DifferentialChannelView`` model).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from gigaevo_client import (
    DifferentialChannelView,
    GigaEvoClient,
    VersionScore,
)


SAMPLE_RESPONSE = {
    "entity_id": "11111111-1111-1111-1111-111111111111",
    "baseline_channel": "stable",
    "baseline_version_id": "v-stable",
    "objective": "fitness_score",
    "baseline_value": 0.61,
    "winners": [
        {
            "version_id": "v-win-1",
            "version_number": 5,
            "value": 0.85,
            "delta": 0.24,
            "author": "mage",
            "created_at": "2026-05-16T11:00:00+00:00",
            "change_summary": "rewrote prompt",
        },
        {
            "version_id": "v-win-2",
            "version_number": 4,
            "value": 0.72,
            "delta": 0.11,
            "author": "platform",
            "created_at": "2026-05-15T09:00:00+00:00",
            "change_summary": None,
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
    def test_url_and_default_params(self, client):
        route = respx.get("http://test/v1/chains/abc-123/versions/beating").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE),
        )
        result = client.list_chain_versions_beating("abc-123")
        assert route.called
        req = route.calls.last.request
        params = dict(req.url.params)
        # Defaults thread through.
        assert params == {
            "channel": "stable",
            "objective": "fitness_score",
            "limit": "50",
            "sort_dir": "desc",
        }
        assert isinstance(result, DifferentialChannelView)

    @respx.mock
    def test_explicit_params_override_defaults(self, client):
        route = respx.get("http://test/v1/chains/xyz-789/versions/beating").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE),
        )
        client.list_chain_versions_beating(
            "xyz-789",
            channel="evolved",
            objective="accuracy",
            limit=10,
            sort_dir="asc",
        )
        params = dict(route.calls.last.request.url.params)
        assert params == {
            "channel": "evolved",
            "objective": "accuracy",
            "limit": "10",
            "sort_dir": "asc",
        }


class TestResponseParsing:
    @respx.mock
    def test_parses_to_typed_model(self, client):
        respx.get("http://test/v1/chains/c1/versions/beating").mock(
            return_value=httpx.Response(200, json=SAMPLE_RESPONSE),
        )
        result = client.list_chain_versions_beating("c1")
        assert isinstance(result, DifferentialChannelView)
        assert result.baseline_value == 0.61
        assert result.objective == "fitness_score"
        assert len(result.winners) == 2
        first = result.winners[0]
        assert isinstance(first, VersionScore)
        assert first.value == 0.85
        assert first.delta == 0.24
        assert first.change_summary == "rewrote prompt"

    @respx.mock
    def test_empty_winners_round_trip(self, client):
        empty = {**SAMPLE_RESPONSE, "baseline_value": None, "winners": []}
        respx.get("http://test/v1/chains/c2/versions/beating").mock(
            return_value=httpx.Response(200, json=empty),
        )
        result = client.list_chain_versions_beating("c2")
        assert result.baseline_value is None
        assert result.winners == []
