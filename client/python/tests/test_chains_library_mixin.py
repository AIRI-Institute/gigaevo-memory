"""Tests for the CARE library extensions on ChainsMixin.

Mirrors ``test_library_mutations_client.py`` (which covered AgentsMixin)
for the chains-side replication shipped in iteration #11.
"""

import json
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlparse

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


def _chain_payload(**ov):
    base = {
        "entity_type": "chain",
        "entity_id": "ch-001",
        "version_id": "v1",
        "channel": "latest",
        "etag": "e1",
        "meta": {"name": "financier-helper"},
        "content": {"version": "1.1", "steps": []},
        "favourite": False,
        "run_count": 0,
        "last_run_at": None,
        "display_name": "financier-helper",
        "description": None,
    }
    base.update(ov)
    return base


class TestChainMarkFavourite:
    def test_mark_chain_favourite_posts_correct_body(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/chains/ch-001/favourite").mock(
                return_value=httpx.Response(200, json=_chain_payload(favourite=True))
            )
            out = client.mark_chain_favourite("ch-001", value=True)
        assert out.favourite is True
        body = json.loads(route.calls.last.request.content)
        assert body == {"favourite": True}

    def test_mark_chain_favourite_404(self, client):
        from gigaevo_memory import NotFoundError

        with respx.mock:
            respx.post("http://test-api:8000/v1/chains/missing/favourite").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"})
            )
            with pytest.raises(NotFoundError):
                client.mark_chain_favourite("missing", value=True)


class TestChainRecordRun:
    def test_record_chain_run_passes_run_id(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/chains/ch-001/run-recorded").mock(
                return_value=httpx.Response(
                    200,
                    json=_chain_payload(
                        run_count=3,
                        last_run_at=datetime(2026, 5, 16, 11, tzinfo=timezone.utc).isoformat(),
                    ),
                )
            )
            out = client.record_chain_run("ch-001", run_id="run-2026-05-16")
        assert out.run_count == 3
        assert out.last_run_at is not None
        body = json.loads(route.calls.last.request.content)
        assert body == {"run_id": "run-2026-05-16"}

    def test_record_chain_run_empty_body_without_run_id(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/chains/ch-001/run-recorded").mock(
                return_value=httpx.Response(200, json=_chain_payload(run_count=1))
            )
            client.record_chain_run("ch-001")
        body = json.loads(route.calls.last.request.content)
        assert body == {}


class TestChainUpdateMetadata:
    def test_update_chain_metadata_sends_only_provided(self, client):
        with respx.mock:
            route = respx.patch("http://test-api:8000/v1/chains/ch-001").mock(
                return_value=httpx.Response(
                    200,
                    json=_chain_payload(display_name="Financier helper"),
                )
            )
            out = client.update_chain_metadata("ch-001", display_name="Financier helper")
        assert out.display_name == "Financier helper"
        body = json.loads(route.calls.last.request.content)
        assert body == {"display_name": "Financier helper"}

    def test_update_chain_metadata_clears_tags_with_empty_list(self, client):
        with respx.mock:
            route = respx.patch("http://test-api:8000/v1/chains/ch-001").mock(
                return_value=httpx.Response(200, json=_chain_payload())
            )
            client.update_chain_metadata("ch-001", tags=[])
        body = json.loads(route.calls.last.request.content)
        assert body == {"tags": []}


class TestEnrichedListChains:
    def test_list_chains_no_params_sends_only_pagination(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_chains()
        url = str(route.calls.last.request.url)
        params = dict(parse_qsl(urlparse(url).query))
        assert params == {"limit": "50", "offset": "0", "channel": "latest"}

    def test_list_chains_all_knobs(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_chains(
                sort_by="last_run_at",
                sort_dir="desc",
                favourites_only=True,
                tags=["finance", "monthly"],
                q="report",
                namespace="glazkov",
            )
        url = str(route.calls.last.request.url)
        parsed = parse_qsl(urlparse(url).query)
        tag_values = [v for k, v in parsed if k == "tags"]
        assert tag_values == ["finance", "monthly"]
        scalar = {k: v for k, v in parsed if k != "tags"}
        assert scalar["sort_by"] == "last_run_at"
        assert scalar["sort_dir"] == "desc"
        assert scalar["favourites_only"].lower() == "true"
        assert scalar["q"] == "report"
        assert scalar["namespace"] == "glazkov"

    def test_list_chains_response_carries_library_metadata(self, client):
        """Returned `EntityResponse`s expose the 5 new fields."""
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        _chain_payload(
                            entity_id="ch-001",
                            favourite=True,
                            run_count=5,
                            display_name="Financier helper",
                            description="Drafts monthly reports.",
                        ),
                    ],
                )
            )
            chains = client.list_chains()
        assert len(chains) == 1
        assert chains[0].favourite is True
        assert chains[0].run_count == 5
        assert chains[0].display_name == "Financier helper"
