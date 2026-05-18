"""Tests for ``list_*_paged`` client methods that consume cursor
pagination via ``X-Next-Cursor`` / ``X-Has-More`` response headers."""

from urllib.parse import parse_qsl, urlparse

import httpx
import pytest
import respx

from gigaevo_memory import MemoryClient


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


def _entity_payload(entity_type: str, entity_id: str) -> dict:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "version_id": "v1",
        "channel": "latest",
        "etag": "e1",
        "meta": {"name": entity_id},
        "content": {"name": entity_id},
        "favourite": False, "run_count": 0, "last_run_at": None,
        "display_name": entity_id, "description": None,
    }


class TestListChainsPaged:
    def test_first_page_no_cursor_param(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(
                    200,
                    json=[_entity_payload("chain", "ch-1")],
                    headers={"X-Next-Cursor": "ABC", "X-Has-More": "true"},
                )
            )
            items, cursor, has_more = client.list_chains_paged()
        assert len(items) == 1
        assert items[0].entity_id == "ch-1"
        assert cursor == "ABC"
        assert has_more is True
        # No cursor sent on first call.
        qs = urlparse(str(route.calls.last.request.url)).query
        assert "cursor=" not in qs

    def test_subsequent_page_carries_cursor(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(
                    200,
                    json=[],
                    headers={"X-Has-More": "false"},
                )
            )
            client.list_chains_paged(cursor="ABC")
        params = dict(parse_qsl(urlparse(str(route.calls.last.request.url)).query))
        assert params["cursor"] == "ABC"

    def test_end_of_stream(self, client):
        with respx.mock:
            respx.get("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(
                    200,
                    json=[_entity_payload("chain", "ch-final")],
                    headers={"X-Has-More": "false"},
                )
            )
            items, cursor, has_more = client.list_chains_paged()
        assert len(items) == 1
        assert cursor is None
        assert has_more is False

    def test_filters_compose_with_paging(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains").mock(
                return_value=httpx.Response(200, json=[],
                                             headers={"X-Has-More": "false"})
            )
            client.list_chains_paged(
                cursor="XYZ",
                limit=25,
                favourites_only=True,
                sort_by="last_run_at",
                sort_dir="desc",
                namespace="glazkov",
                tags=["finance"],
            )
        params = dict(parse_qsl(urlparse(str(route.calls.last.request.url)).query))
        assert params["cursor"] == "XYZ"
        assert params["limit"] == "25"
        assert params["favourites_only"].lower() == "true"
        assert params["sort_by"] == "last_run_at"


class TestListAgentsPaged:
    def test_returns_tuple(self, client):
        with respx.mock:
            respx.get("http://test-api:8000/v1/agents").mock(
                return_value=httpx.Response(
                    200,
                    json=[_entity_payload("agent", "ag-1")],
                    headers={"X-Next-Cursor": "AG-CURSOR", "X-Has-More": "true"},
                )
            )
            out = client.list_agents_paged()
        assert isinstance(out, tuple) and len(out) == 3
        items, cursor, has_more = out
        assert items[0].entity_id == "ag-1"
        assert cursor == "AG-CURSOR"
        assert has_more is True


class TestListAgentSkillsPaged:
    def test_with_tool_filter_returns_no_cursor(self, client):
        """Server side suppresses cursor under tool filter — client surfaces that."""
        with respx.mock:
            respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(
                    200,
                    json=[],
                    headers={"X-Has-More": "false"},  # server suppressed cursor
                )
            )
            items, cursor, has_more = client.list_agent_skills_paged(
                excludes_tools=["Bash(python:*)"],
            )
        assert cursor is None
        assert has_more is False

    def test_tool_filter_sent_as_repeated_param(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[],
                                             headers={"X-Has-More": "false"})
            )
            client.list_agent_skills_paged(
                requires_tools=["Read", "Write"]
            )
        pairs = parse_qsl(urlparse(str(route.calls.last.request.url)).query)
        tool_vals = [v for k, v in pairs if k == "requires_tool"]
        assert tool_vals == ["Read", "Write"]


class TestCursorIteration:
    """End-to-end: simulate walking a 3-page library."""

    def test_three_page_walk(self, client):
        page_responses = [
            httpx.Response(200, json=[_entity_payload("chain", f"ch-{i}")
                                        for i in (1, 2, 3)],
                           headers={"X-Next-Cursor": "C-PAGE-2",
                                    "X-Has-More": "true"}),
            httpx.Response(200, json=[_entity_payload("chain", f"ch-{i}")
                                        for i in (4, 5, 6)],
                           headers={"X-Next-Cursor": "C-PAGE-3",
                                    "X-Has-More": "true"}),
            httpx.Response(200, json=[_entity_payload("chain", "ch-7")],
                           headers={"X-Has-More": "false"}),
        ]
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/chains")
            route.side_effect = page_responses

            all_ids: list[str] = []
            cursor: str | None = None
            for _ in range(5):  # safety guard against infinite loop
                items, cursor, has_more = client.list_chains_paged(cursor=cursor)
                all_ids.extend(it.entity_id for it in items)
                if not has_more:
                    break

        assert all_ids == [f"ch-{i}" for i in range(1, 8)]
