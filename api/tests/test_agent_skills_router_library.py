"""Tests for the CARE library backbone on the agent_skills router.

Closes the §1.4 backbone for the third typed entity type (after agents
in iter #7-8 and chains in iter #11).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import uuid

from app.db.models import Entity


def _stub_skill_entity(**overrides) -> Entity:
    base = dict(
        entity_id=uuid.uuid4(),
        entity_type="agent_skill",
        namespace="glazkov",
        name="pdf",
        tags=[],
        when_to_use=None,
        channels={"latest": str(uuid.uuid4())},
        deleted_at=None,
        favourite=False,
        run_count=0,
        last_run_at=None,
        display_name="pdf",
        description=None,
    )
    base.update(overrides)
    return Entity(**base)


class TestAgentSkillsRouterRegistration:
    def test_router_has_patch_and_mutation_routes(self):
        from app.routers.agent_skills import router

        paths_methods = {
            (route.path, method)
            for route in router.routes
            for method in getattr(route, "methods", ())
        }
        assert ("/v1/agent-skills/{agent_skill_id}", "PATCH") in paths_methods
        assert ("/v1/agent-skills/{agent_skill_id}/favourite", "POST") in paths_methods
        assert ("/v1/agent-skills/{agent_skill_id}/run-recorded", "POST") in paths_methods

    def test_openapi_lists_new_endpoints(self):
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/v1/agent-skills/{agent_skill_id}" in paths
        assert "patch" in paths["/v1/agent-skills/{agent_skill_id}"]
        assert "/v1/agent-skills/{agent_skill_id}/favourite" in paths
        assert "/v1/agent-skills/{agent_skill_id}/run-recorded" in paths

    def test_agent_skills_list_exposes_library_query_params(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/agent-skills"]["get"]["parameters"]
        }
        for name in ("sort_by", "sort_dir", "favourites_only", "tags", "q", "namespace"):
            assert name in params, f"Missing {name} on GET /v1/agent-skills"

    def test_list_defaults_match_care_catalogue(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/agent-skills"]["get"]["parameters"]
        }
        assert params["sort_by"]["schema"]["default"] == "last_run_at"
        assert params["sort_dir"]["schema"]["default"] == "desc"
        assert params["favourites_only"]["schema"]["default"] is False


class TestAgentSkillResponseHelper:
    def test_response_helper_surfaces_library_fields(self):
        """`_agent_skill_response` plumbs the 5 library-metadata fields."""
        from app.routers.agent_skills import _agent_skill_response

        entity = _stub_skill_entity(
            favourite=True,
            run_count=8,
            last_run_at=datetime(2026, 5, 16, 12, tzinfo=timezone.utc),
            display_name="PDF skill",
            description="Extract structured data from PDFs.",
        )
        version = MagicMock(
            version_id=uuid.uuid4(),
            content_json={"name": "pdf", "uri": "github://anthropics/skills/skills/pdf@main"},
            meta_json={"author": "mage"},
        )
        resp = _agent_skill_response(entity, version, channel="latest")
        assert resp.entity_type == "agent_skill"
        assert resp.favourite is True
        assert resp.run_count == 8
        assert resp.last_run_at == datetime(2026, 5, 16, 12, tzinfo=timezone.utc)
        assert resp.display_name == "PDF skill"
        assert resp.description == "Extract structured data from PDFs."
        assert resp.etag
        assert resp.meta == {"author": "mage"}
