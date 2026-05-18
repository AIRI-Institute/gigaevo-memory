"""Tests for the CARE library-mutation client methods.

Covers ``MemoryClient.mark_favourite`` / ``record_run`` /
``update_metadata`` (the three mutation endpoints landed in iteration #7
on the agents router) and the enriched ``list_agents`` (iteration #8's
sort/filter knobs).
"""

import json
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlparse

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient
from gigaevo_memory.models import EntityResponse


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


def _agent_payload(**overrides) -> dict:
    """Build a server response payload matching the agents router's shape."""
    base = {
        "entity_type": "agent",
        "entity_id": "agent-001",
        "version_id": "ver-1",
        "channel": "latest",
        "etag": "etag-1",
        "meta": {"name": "financier"},
        "content": {"role": "Drafts monthly reports."},
        "favourite": False,
        "run_count": 0,
        "last_run_at": None,
        "display_name": "financier",
        "description": None,
    }
    base.update(overrides)
    return base


class TestMarkFavourite:
    def test_mark_favourite_true_posts_correct_body(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agents/agent-001/favourite").mock(
                return_value=httpx.Response(200, json=_agent_payload(favourite=True))
            )
            out = client.mark_favourite("agent-001", value=True)

        assert isinstance(out, EntityResponse)
        assert out.favourite is True
        body = json.loads(route.calls.last.request.content)
        assert body == {"favourite": True}

    def test_mark_favourite_false_unstars(self, client):
        with respx.mock:
            respx.post("http://test-api:8000/v1/agents/agent-001/favourite").mock(
                return_value=httpx.Response(200, json=_agent_payload(favourite=False))
            )
            out = client.mark_favourite("agent-001", value=False)
        assert out.favourite is False

    def test_mark_favourite_404_raises(self, client):
        from gigaevo_memory import NotFoundError

        with respx.mock:
            respx.post("http://test-api:8000/v1/agents/missing/favourite").mock(
                return_value=httpx.Response(404, json={"detail": "Not found"})
            )
            with pytest.raises(NotFoundError):
                client.mark_favourite("missing", value=True)


class TestRecordRun:
    def test_record_run_without_run_id_sends_empty_body(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agents/agent-001/run-recorded").mock(
                return_value=httpx.Response(
                    200,
                    json=_agent_payload(
                        run_count=1,
                        last_run_at=datetime(2026, 5, 16, 10, tzinfo=timezone.utc).isoformat(),
                    ),
                )
            )
            out = client.record_run("agent-001")

        assert out.run_count == 1
        assert out.last_run_at is not None
        body = json.loads(route.calls.last.request.content)
        assert body == {}

    def test_record_run_passes_run_id_when_provided(self, client):
        with respx.mock:
            route = respx.post("http://test-api:8000/v1/agents/agent-001/run-recorded").mock(
                return_value=httpx.Response(200, json=_agent_payload(run_count=2))
            )
            client.record_run("agent-001", run_id="run-xyz")

        body = json.loads(route.calls.last.request.content)
        assert body == {"run_id": "run-xyz"}


class TestUpdateMetadata:
    def test_update_metadata_sends_only_provided_fields(self, client):
        """`tags`/`description`/`favourite` omitted → not in body (partial PATCH)."""
        with respx.mock:
            route = respx.patch("http://test-api:8000/v1/agents/agent-001").mock(
                return_value=httpx.Response(
                    200,
                    json=_agent_payload(display_name="Financier helper"),
                )
            )
            out = client.update_metadata("agent-001", display_name="Financier helper")

        assert out.display_name == "Financier helper"
        body = json.loads(route.calls.last.request.content)
        assert body == {"display_name": "Financier helper"}
        # Crucially, omitted fields are NOT sent — they'd accidentally
        # null-out the server's stored values.
        assert "description" not in body
        assert "tags" not in body
        assert "favourite" not in body

    def test_update_metadata_empty_tags_clears(self, client):
        """`tags=[]` is distinct from omitting — it explicitly clears tags."""
        with respx.mock:
            route = respx.patch("http://test-api:8000/v1/agents/agent-001").mock(
                return_value=httpx.Response(200, json=_agent_payload())
            )
            client.update_metadata("agent-001", tags=[])

        body = json.loads(route.calls.last.request.content)
        assert body == {"tags": []}

    def test_update_metadata_all_fields(self, client):
        with respx.mock:
            route = respx.patch("http://test-api:8000/v1/agents/agent-001").mock(
                return_value=httpx.Response(200, json=_agent_payload(favourite=True))
            )
            client.update_metadata(
                "agent-001",
                display_name="Helper",
                description="d",
                tags=["a", "b"],
                favourite=True,
            )

        body = json.loads(route.calls.last.request.content)
        assert body == {
            "display_name": "Helper",
            "description": "d",
            "tags": ["a", "b"],
            "favourite": True,
        }


class TestEnrichedListAgents:
    """The new sort/filter knobs propagate as query params."""

    def test_no_params_sends_only_pagination_defaults(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agents").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agents()

        url = route.calls.last.request.url
        params = dict(parse_qsl(urlparse(str(url)).query))
        # Only baseline pagination params.
        assert params == {"limit": "50", "offset": "0", "channel": "latest"}

    def test_all_knobs_sent_as_query_params(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agents").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agents(
                sort_by="last_run_at",
                sort_dir="desc",
                favourites_only=True,
                tags=["pdf", "extraction"],
                q="financier",
                namespace="glazkov",
            )

        url = str(route.calls.last.request.url)
        parsed = parse_qsl(urlparse(url).query)
        # Repeated `tags=…` query params for AND-filter semantics.
        tag_values = [v for k, v in parsed if k == "tags"]
        assert tag_values == ["pdf", "extraction"]
        # Other knobs as scalars.
        scalar = {k: v for k, v in parsed if k != "tags"}
        assert scalar["sort_by"] == "last_run_at"
        assert scalar["sort_dir"] == "desc"
        assert scalar["favourites_only"].lower() == "true"
        assert scalar["q"] == "financier"
        assert scalar["namespace"] == "glazkov"

    def test_response_carries_library_metadata(self, client):
        """Server returns the 5 new fields; the client parses them."""
        with respx.mock:
            respx.get("http://test-api:8000/v1/agents").mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        _agent_payload(
                            entity_id="agent-001",
                            favourite=True,
                            run_count=7,
                            last_run_at=datetime(2026, 5, 16, 9, tzinfo=timezone.utc).isoformat(),
                            display_name="Financier helper",
                            description="Drafts monthly reports.",
                        ),
                    ],
                )
            )
            out = client.list_agents()

        assert len(out) == 1
        agent = out[0]
        assert agent.favourite is True
        assert agent.run_count == 7
        assert agent.last_run_at is not None
        assert agent.display_name == "Financier helper"
        assert agent.description == "Drafts monthly reports."

    def test_empty_tags_list_does_not_send_tags_param(self, client):
        """`tags=[]` should be elided (matches server-side semantics)."""
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agents").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agents(tags=[])

        url = str(route.calls.last.request.url)
        assert "tags=" not in urlparse(url).query
