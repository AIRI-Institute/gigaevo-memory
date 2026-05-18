"""Tests for the allowed_tools faceted filter on the client side."""

from urllib.parse import parse_qsl, urlparse

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


class TestRequiresExcludesQueryParams:
    def test_requires_tools_sent_as_repeated_param(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills(requires_tools=["Read", "Write"])
        url = str(route.calls.last.request.url)
        pairs = parse_qsl(urlparse(url).query)
        req_values = [v for k, v in pairs if k == "requires_tool"]
        assert req_values == ["Read", "Write"]

    def test_excludes_tools_sent_as_repeated_param(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills(excludes_tools=["Bash(python:*)"])
        url = str(route.calls.last.request.url)
        pairs = parse_qsl(urlparse(url).query)
        exc_values = [v for k, v in pairs if k == "excludes_tool"]
        assert exc_values == ["Bash(python:*)"]

    def test_both_filters_combined(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills(
                requires_tools=["WebFetch(domain:api.openweathermap.org)"],
                excludes_tools=["Bash(python:*)"],
            )
        url = str(route.calls.last.request.url)
        pairs = parse_qsl(urlparse(url).query)
        assert [v for k, v in pairs if k == "requires_tool"] == [
            "WebFetch(domain:api.openweathermap.org)"
        ]
        assert [v for k, v in pairs if k == "excludes_tool"] == ["Bash(python:*)"]

    def test_empty_lists_elided(self, client):
        """Empty lists must NOT appear as `requires_tool=` (which would
        send an empty string and confuse the server-side regex)."""
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills(requires_tools=[], excludes_tools=[])
        qstr = urlparse(str(route.calls.last.request.url)).query
        assert "requires_tool=" not in qstr
        assert "excludes_tool=" not in qstr

    def test_no_kwargs_sends_no_tool_params(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills()
        qstr = urlparse(str(route.calls.last.request.url)).query
        assert "requires_tool=" not in qstr
        assert "excludes_tool=" not in qstr

    def test_existing_knobs_still_work_alongside_tool_filters(self, client):
        """Tool filters compose with the existing sort/filter knobs."""
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills(
                favourites_only=True,
                sort_by="run_count",
                sort_dir="desc",
                tags=["pdf"],
                excludes_tools=["Bash"],
            )
        pairs = parse_qsl(urlparse(str(route.calls.last.request.url)).query)
        params = {k: v for k, v in pairs}
        assert params["favourites_only"].lower() == "true"
        assert params["sort_by"] == "run_count"
        assert params["sort_dir"] == "desc"
        assert any(k == "tags" and v == "pdf" for k, v in pairs)
        assert any(k == "excludes_tool" and v == "Bash" for k, v in pairs)
