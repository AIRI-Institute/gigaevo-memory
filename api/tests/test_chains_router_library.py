"""Tests for the CARE library backbone on the chains router.

Mirrors ``test_library_mutations.py`` (which covered the agents router)
plus ``test_library_list_query.py`` (which covered list query params).
This file focuses specifically on the chains-router replication shipped
in iteration #11.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import uuid

from app.db.models import Entity


def _stub_entity(**overrides) -> Entity:
    base = dict(
        entity_id=uuid.uuid4(),
        entity_type="chain",
        namespace="glazkov",
        name="financier-helper",
        tags=[],
        when_to_use=None,
        channels={"latest": str(uuid.uuid4())},
        deleted_at=None,
        favourite=False,
        run_count=0,
        last_run_at=None,
        display_name="financier-helper",
        description=None,
    )
    base.update(overrides)
    return Entity(**base)


class TestChainsRouterRegistration:
    def test_router_has_patch_and_mutation_routes(self):
        from app.routers.chains import router

        paths_methods = {
            (route.path, method)
            for route in router.routes
            for method in getattr(route, "methods", ())
        }
        assert ("/v1/chains/{chain_id}", "PATCH") in paths_methods
        assert ("/v1/chains/{chain_id}/favourite", "POST") in paths_methods
        assert ("/v1/chains/{chain_id}/run-recorded", "POST") in paths_methods

    def test_openapi_lists_new_endpoints(self):
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/v1/chains/{chain_id}" in paths
        assert "patch" in paths["/v1/chains/{chain_id}"]
        assert "/v1/chains/{chain_id}/favourite" in paths
        assert "/v1/chains/{chain_id}/run-recorded" in paths

    def test_chains_list_exposes_library_query_params(self):
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/chains"]["get"]["parameters"]
        }
        # Same six knobs the agents router exposes.
        for name in ("sort_by", "sort_dir", "favourites_only", "tags", "q", "namespace"):
            assert name in params, f"Missing {name} on GET /v1/chains"

    def test_list_defaults_match_care_library(self):
        """Default sort matches the LibraryScreen's home view."""
        from app.main import app

        params = {
            p["name"]: p
            for p in app.openapi()["paths"]["/v1/chains"]["get"]["parameters"]
        }
        assert params["sort_by"]["schema"]["default"] == "last_run_at"
        assert params["sort_dir"]["schema"]["default"] == "desc"
        assert params["favourites_only"]["schema"]["default"] is False


class TestChainResponseHelper:
    def test_chain_response_surfaces_library_fields(self):
        """`_chain_response` plumbs the 5 library-metadata fields."""
        from app.routers.chains import _chain_response

        entity = _stub_entity(
            favourite=True,
            run_count=4,
            last_run_at=datetime(2026, 5, 16, 9, tzinfo=timezone.utc),
            display_name="Financier helper",
            description="Drafts monthly reports.",
        )
        version = MagicMock(
            version_id=uuid.uuid4(),
            content_json={"version": "1.1", "steps": []},
            meta_json={"author": "mage"},
        )
        resp = _chain_response(entity, version, channel="latest")
        assert resp.entity_type == "chain"
        assert resp.favourite is True
        assert resp.run_count == 4
        assert resp.last_run_at == datetime(2026, 5, 16, 9, tzinfo=timezone.utc)
        assert resp.display_name == "Financier helper"
        assert resp.description == "Drafts monthly reports."
        # Etag derived from content; meta_json passes through.
        assert resp.etag
        assert resp.meta == {"author": "mage"}
