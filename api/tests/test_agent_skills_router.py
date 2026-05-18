"""Unit tests for the agent_skills router registration.

These tests verify the agent_skills router is wired into the FastAPI app
without requiring a live database. End-to-end CRUD coverage lives in
``test_api_crud.py`` (integration suite).
"""

from app.main import app
from app.models.responses import AgentSkillPageResponse, AgentSkillResponse
from app.routers.agent_skills import router as agent_skills_router


class TestAgentSkillsRouter:
    """Verify the agent_skills router is exposed correctly."""

    def test_router_prefix_and_tags(self):
        """Router uses kebab-case URL prefix and snake_case tag."""
        assert agent_skills_router.prefix == "/v1/agent-skills"
        assert "agent_skills" in agent_skills_router.tags

    def test_router_exposes_full_crud_surface(self):
        """All five typed CRUD endpoints (list/create/get/update/delete) are present."""
        paths_methods = {
            (route.path, method)
            for route in agent_skills_router.routes
            for method in getattr(route, "methods", ())
        }
        # APIRouter bakes the prefix into each route's path at registration
        # time, so paths_methods carries the fully-qualified URL.
        assert ("/v1/agent-skills", "POST") in paths_methods
        assert ("/v1/agent-skills", "GET") in paths_methods
        assert ("/v1/agent-skills/{agent_skill_id}", "GET") in paths_methods
        assert ("/v1/agent-skills/{agent_skill_id}", "PUT") in paths_methods
        assert ("/v1/agent-skills/{agent_skill_id}", "DELETE") in paths_methods

    def test_router_mounted_on_app(self):
        """FastAPI app exposes /v1/agent-skills paths in its full route table."""
        full_paths = {route.path for route in app.routes}
        assert "/v1/agent-skills" in full_paths
        assert "/v1/agent-skills/{agent_skill_id}" in full_paths

    def test_openapi_exposes_agent_skills(self):
        """OpenAPI schema lists the agent_skills paths and the response model."""
        schema = app.openapi()
        assert "/v1/agent-skills" in schema["paths"]
        assert "/v1/agent-skills/{agent_skill_id}" in schema["paths"]
        # Response model component is registered.
        assert "AgentSkillResponse" in schema["components"]["schemas"]


class TestAgentSkillResponseModel:
    """The new Pydantic response models behave like their siblings."""

    def test_agent_skill_response_entity_type_literal(self):
        """`entity_type` defaults to the 'agent_skill' literal."""
        resp = AgentSkillResponse(
            entity_id="00000000-0000-0000-0000-000000000000",
            version_id="00000000-0000-0000-0000-000000000001",
            channel="latest",
            etag="abc",
            meta={},
            content={"name": "pdf", "uri": "github://anthropics/skills/skills/pdf"},
        )
        assert resp.entity_type == "agent_skill"

    def test_agent_skill_response_rejects_wrong_literal(self):
        """Passing a non-agent_skill literal is rejected by Pydantic."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AgentSkillResponse(
                entity_type="agent",  # wrong literal
                entity_id="00000000-0000-0000-0000-000000000000",
                version_id="00000000-0000-0000-0000-000000000001",
                channel="latest",
                etag="abc",
                meta={},
                content={},
            )

    def test_agent_skill_page_response_empty_default(self):
        """Page response defaults to empty items list."""
        page = AgentSkillPageResponse()
        assert page.items == []
        assert page.has_more is False
        assert page.next_cursor is None
