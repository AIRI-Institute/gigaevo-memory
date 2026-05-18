"""Tests for ``MemoryClient.get_chain_lineage``."""

from urllib.parse import parse_qsl, urlparse

import httpx
import pytest
import respx

from gigaevo_memory import LineageResponse, LineageVersion, MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


def _v(version_id: str, *, version_number: int, parents: list[str] | None = None,
       depth: int = 0, evolution_meta: dict | None = None) -> dict:
    return {
        "version_id": version_id,
        "version_number": version_number,
        "parents": parents or [],
        "evolution_meta": evolution_meta,
        "change_summary": None,
        "author": None,
        "created_at": "2026-05-16T12:00:00+00:00",
        "depth": depth,
    }


def _lineage_payload(*versions: dict, root_id: str | None = None,
                     entity_id: str = "ch-001",
                     max_depth_reached: bool = False) -> dict:
    return {
        "entity_id": entity_id,
        "root_version_id": root_id or versions[0]["version_id"],
        "versions": list(versions),
        "max_depth_reached": max_depth_reached,
    }


class TestGetChainLineageRequest:
    def test_default_params(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains/ch-001/lineage").mock(
                return_value=httpx.Response(
                    200,
                    json=_lineage_payload(_v("v0", version_number=0)),
                )
            )
            client.get_chain_lineage("ch-001")
        url = str(route.calls.last.request.url)
        params = dict(parse_qsl(urlparse(url).query))
        assert params == {"channel": "latest", "max_depth": "10"}

    def test_explicit_version_id(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains/ch-001/lineage").mock(
                return_value=httpx.Response(
                    200,
                    json=_lineage_payload(_v("v1", version_number=1)),
                )
            )
            client.get_chain_lineage("ch-001", version_id="v1", max_depth=5)
        url = str(route.calls.last.request.url)
        params = dict(parse_qsl(urlparse(url).query))
        assert params == {"channel": "latest", "max_depth": "5", "version_id": "v1"}

    def test_custom_channel(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains/ch-001/lineage").mock(
                return_value=httpx.Response(
                    200,
                    json=_lineage_payload(_v("v0", version_number=0)),
                )
            )
            client.get_chain_lineage("ch-001", channel="stable")
        url = str(route.calls.last.request.url)
        params = dict(parse_qsl(urlparse(url).query))
        assert params["channel"] == "stable"


class TestLineageResponseParsing:
    def test_returns_typed_response(self, client):
        payload = _lineage_payload(
            _v("v3", version_number=3, parents=["v2"], depth=0,
               evolution_meta={"fitness_score": 0.87}),
            _v("v2", version_number=2, parents=["v1"], depth=1),
            _v("v1", version_number=1, parents=[], depth=2),
        )
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/ch-001/lineage").mock(
                return_value=httpx.Response(200, json=payload)
            )
            out = client.get_chain_lineage("ch-001")
        assert isinstance(out, LineageResponse)
        assert out.entity_id == "ch-001"
        assert out.root_version_id == "v3"
        assert len(out.versions) == 3
        assert isinstance(out.versions[0], LineageVersion)
        assert out.versions[0].evolution_meta == {"fitness_score": 0.87}
        # Depth ordering preserved.
        assert [v.depth for v in out.versions] == [0, 1, 2]

    def test_dedup_diamond(self, client):
        """Diamond ancestry: a & b both feed c which feeds d."""
        payload = _lineage_payload(
            _v("d", version_number=3, parents=["c"], depth=0),
            _v("c", version_number=2, parents=["a", "b"], depth=1),
            _v("a", version_number=1, parents=[], depth=2),
            _v("b", version_number=0, parents=[], depth=2),
        )
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/ch-001/lineage").mock(
                return_value=httpx.Response(200, json=payload)
            )
            out = client.get_chain_lineage("ch-001")
        assert {v.version_id for v in out.versions} == {"a", "b", "c", "d"}
        # c is the multi-parent crossover; reachable from both a and b paths.
        c_node = next(v for v in out.versions if v.version_id == "c")
        assert sorted(c_node.parents) == ["a", "b"]

    def test_max_depth_reached_flag(self, client):
        payload = _lineage_payload(
            _v("d", version_number=3, parents=["c"], depth=0),
            _v("c", version_number=2, parents=["b"], depth=1),
            max_depth_reached=True,
        )
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/ch-001/lineage").mock(
                return_value=httpx.Response(200, json=payload)
            )
            out = client.get_chain_lineage("ch-001", max_depth=1)
        assert out.max_depth_reached is True


class TestLineage404:
    def test_404_raises_not_found(self, client):
        from gigaevo_memory import NotFoundError

        with respx.mock:
            respx.get("http://test-api:8000/v1/chains/missing/lineage").mock(
                return_value=httpx.Response(404, json={"detail": "Chain not found"})
            )
            with pytest.raises(NotFoundError):
                client.get_chain_lineage("missing")
