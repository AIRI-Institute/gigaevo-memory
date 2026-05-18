"""Tests for the CARE library extensions on AgentSkillsMixin."""

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


def _skill_payload(**ov):
    base = {
        "entity_type": "agent_skill",
        "entity_id": "sk-pdf-001",
        "version_id": "v1",
        "channel": "latest",
        "etag": "e1",
        "meta": {"name": "pdf"},
        "content": {"name": "pdf", "uri": "github://anthropics/skills/skills/pdf@main"},
        "favourite": False,
        "run_count": 0,
        "last_run_at": None,
        "display_name": "pdf",
        "description": None,
    }
    base.update(ov)
    return base


class TestMarkAgentSkillFavourite:
    def test_mark_skill_favourite(self, client):
        with respx.mock:
            route = respx.post(
                "http://test-api:8000/v1/agent-skills/sk-pdf-001/favourite"
            ).mock(
                return_value=httpx.Response(200, json=_skill_payload(favourite=True))
            )
            out = client.mark_agent_skill_favourite("sk-pdf-001", value=True)
        assert out.favourite is True
        body = json.loads(route.calls.last.request.content)
        assert body == {"favourite": True}

    def test_mark_skill_favourite_404(self, client):
        from gigaevo_memory import NotFoundError

        with respx.mock:
            respx.post(
                "http://test-api:8000/v1/agent-skills/missing/favourite"
            ).mock(return_value=httpx.Response(404, json={"detail": "Not found"}))
            with pytest.raises(NotFoundError):
                client.mark_agent_skill_favourite("missing", value=True)


class TestRecordAgentSkillRun:
    def test_record_skill_run_with_run_id(self, client):
        with respx.mock:
            route = respx.post(
                "http://test-api:8000/v1/agent-skills/sk-pdf-001/run-recorded"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json=_skill_payload(
                        run_count=4,
                        last_run_at=datetime(2026, 5, 16, 12, tzinfo=timezone.utc).isoformat(),
                    ),
                )
            )
            out = client.record_agent_skill_run("sk-pdf-001", run_id="run-7")
        assert out.run_count == 4
        body = json.loads(route.calls.last.request.content)
        assert body == {"run_id": "run-7"}

    def test_record_skill_run_empty_body(self, client):
        with respx.mock:
            route = respx.post(
                "http://test-api:8000/v1/agent-skills/sk-pdf-001/run-recorded"
            ).mock(return_value=httpx.Response(200, json=_skill_payload(run_count=1)))
            client.record_agent_skill_run("sk-pdf-001")
        body = json.loads(route.calls.last.request.content)
        assert body == {}


class TestUpdateAgentSkillMetadata:
    def test_partial_update(self, client):
        with respx.mock:
            route = respx.patch("http://test-api:8000/v1/agent-skills/sk-pdf-001").mock(
                return_value=httpx.Response(200, json=_skill_payload(display_name="PDF skill"))
            )
            out = client.update_agent_skill_metadata("sk-pdf-001", display_name="PDF skill")
        assert out.display_name == "PDF skill"
        body = json.loads(route.calls.last.request.content)
        assert body == {"display_name": "PDF skill"}

    def test_empty_tags_clears(self, client):
        with respx.mock:
            route = respx.patch("http://test-api:8000/v1/agent-skills/sk-pdf-001").mock(
                return_value=httpx.Response(200, json=_skill_payload())
            )
            client.update_agent_skill_metadata("sk-pdf-001", tags=[])
        body = json.loads(route.calls.last.request.content)
        assert body == {"tags": []}


class TestEnrichedListAgentSkills:
    def test_list_no_params_sends_only_pagination(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills()
        url = str(route.calls.last.request.url)
        params = dict(parse_qsl(urlparse(url).query))
        assert params == {"limit": "50", "offset": "0", "channel": "latest"}

    def test_list_all_knobs(self, client):
        with respx.mock:
            route = respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(200, json=[])
            )
            client.list_agent_skills(
                sort_by="last_run_at",
                sort_dir="desc",
                favourites_only=True,
                tags=["pdf", "extraction"],
                q="PDF",
                namespace="glazkov",
            )
        url = str(route.calls.last.request.url)
        parsed = parse_qsl(urlparse(url).query)
        tag_values = [v for k, v in parsed if k == "tags"]
        assert tag_values == ["pdf", "extraction"]
        scalar = {k: v for k, v in parsed if k != "tags"}
        assert scalar["sort_by"] == "last_run_at"
        assert scalar["sort_dir"] == "desc"
        assert scalar["favourites_only"].lower() == "true"
        assert scalar["q"] == "PDF"
        assert scalar["namespace"] == "glazkov"

    def test_response_carries_library_metadata(self, client):
        with respx.mock:
            respx.get("http://test-api:8000/v1/agent-skills").mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        _skill_payload(
                            entity_id="sk-pdf-001",
                            favourite=True,
                            run_count=12,
                            display_name="PDF skill",
                            description="Extract structured data from PDFs.",
                        ),
                    ],
                )
            )
            skills = client.list_agent_skills()
        assert len(skills) == 1
        s = skills[0]
        assert s.favourite is True
        assert s.run_count == 12
        assert s.display_name == "PDF skill"
        assert s.description == "Extract structured data from PDFs."
