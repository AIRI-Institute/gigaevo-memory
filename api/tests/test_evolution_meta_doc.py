"""Doc-drift guard for ``docs/EVOLUTION_META.md`` (TODO §9 P2).

Pins the spec doc against the live source of truth — the
``EvolutionMeta`` Pydantic model (server + client), the
``_maybe_promote_evolved_channel`` rules, the
``GET /v1/chains/{id}/lineage`` endpoint signature, and the
``LineageResponse`` / ``LineageVersion`` shapes.

Structural facts only — we don't pin prose.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOC_PATH = REPO_ROOT / "docs" / "EVOLUTION_META.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.is_file(), f"Doc missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# EvolutionMeta schema fields
# ---------------------------------------------------------------------------


class TestStandardisedFields:
    STANDARDISED = (
        "parent_version_ids",
        "fitness_score",
        "generation",
        "experiment_id",
        "objectives",
        "mutation_kind",
    )

    def test_doc_lists_every_standardised_field(self, doc_text):
        for field in self.STANDARDISED:
            assert f"`{field}`" in doc_text, field

    def test_standardised_fields_exist_on_model(self):
        from app.models.requests import EvolutionMeta

        for field in self.STANDARDISED:
            assert field in EvolutionMeta.model_fields, field


class TestLegacyFields:
    LEGACY = (
        "prompt_ref",
        "fitness",
        "is_valid",
        "metrics",
        "behavioral_descriptors",
    )

    def test_doc_lists_every_legacy_field(self, doc_text):
        for field in self.LEGACY:
            assert f"`{field}`" in doc_text, field

    def test_legacy_fields_still_on_model(self):
        """Legacy fields must remain — pre-2026 JSONB rows depend on
        the model accepting them without coercion."""
        from app.models.requests import EvolutionMeta

        for field in self.LEGACY:
            assert field in EvolutionMeta.model_fields, field


class TestModelMirror:
    def test_client_mirrors_server_field_set(self):
        """The client-side ``EvolutionMeta`` must carry the same
        public field set the server publishes — otherwise CARE's
        round-trip silently drops fields."""
        sys.path.insert(0, str(REPO_ROOT / "client" / "python" / "src"))
        from app.models.requests import EvolutionMeta as ServerEM
        from gigaevo_client.models import EvolutionMeta as ClientEM

        server_fields = set(ServerEM.model_fields)
        client_fields = set(ClientEM.model_fields)
        assert server_fields == client_fields, (
            f"server-only: {server_fields - client_fields}, "
            f"client-only: {client_fields - server_fields}"
        )


# ---------------------------------------------------------------------------
# `evolved` channel auto-promotion rules
# ---------------------------------------------------------------------------


class TestEvolvedChannelRules:
    RULE_KEYWORDS = (
        "No fitness",  # rule 1: no-op
        "No `evolved` channel yet",  # rule 2: first-evolution
        "missing or unparsable",  # rule 3: corrupt pointer
        "New fitness > current",  # rule 4: promote
        "leave the pin alone",  # rule 5: regression keeps incumbent
    )

    def test_all_rules_described(self, doc_text):
        for kw in self.RULE_KEYWORDS:
            assert kw in doc_text, kw

    def test_strict_gt_called_out(self, doc_text):
        """The strict `>` (rather than `>=`) is load-bearing — a re-run
        with identical score must not churn the pointer."""
        assert "Strict `>`" in doc_text or "strict `>`" in doc_text

    def test_helper_uses_strict_gt(self):
        """Pin the doc against the actual implementation: the helper
        must compare with `>` not `>=`."""
        import inspect

        from app.services.entity_service import EntityService

        src = inspect.getsource(EntityService._maybe_promote_evolved_channel)
        assert "new_score > current_score" in src, src

    def test_extraction_prefers_fitness_score_alias(self, doc_text):
        """Doc claims `fitness_score` wins over the legacy `fitness`.
        Confirm the helper actually does that."""
        import inspect

        from app.services.entity_service import EntityService

        src = inspect.getsource(EntityService._extract_fitness)
        # The helper reads fitness_score first, falls back to fitness.
        fs_idx = src.find("fitness_score")
        legacy_idx = src.find('"fitness"')
        assert fs_idx >= 0 and legacy_idx >= 0
        assert fs_idx < legacy_idx, "_extract_fitness must check fitness_score before fitness"


# ---------------------------------------------------------------------------
# Lineage endpoint signature
# ---------------------------------------------------------------------------


class TestLineageEndpoint:
    def test_doc_references_endpoint_path(self, doc_text):
        assert "GET /v1/chains/{chain_id}/lineage" in doc_text or "GET /v1/chains/{id}/lineage" in doc_text

    def test_endpoint_registered_with_documented_path(self):
        from app.routers import chains as chains_router

        lineage_paths = [
            r.path  # type: ignore[attr-defined]
            for r in chains_router.router.routes
            if "lineage" in r.path  # type: ignore[attr-defined]
        ]
        assert lineage_paths == ["/v1/chains/{chain_id}/lineage"], lineage_paths

    def test_documented_query_params_present(self, doc_text):
        for param in ("channel", "version_id", "max_depth"):
            assert f"`{param}`" in doc_text, param

    def test_max_depth_bounds_documented(self, doc_text):
        # Doc claims range 1–100. Endpoint enforces it via Query(ge=1, le=100).
        assert "1`–`100" in doc_text or "(1, 100)" in doc_text or "1`-`100" in doc_text or "1`–`100`" in doc_text

    def test_max_depth_bounds_match_endpoint(self):
        import inspect

        from app.routers.chains import get_chain_lineage

        sig = inspect.signature(get_chain_lineage)
        query = sig.parameters["max_depth"].default
        # FastAPI Query(10, ge=1, le=100) stores the default scalar on
        # `default` and the ge/le constraints as annotated metadata
        # items (e.g. `Ge(ge=1)`, `Le(le=100)`) in `metadata`.
        assert getattr(query, "default", None) == 10
        bounds: dict[str, int] = {}
        for item in getattr(query, "metadata", []) or []:
            if hasattr(item, "ge"):
                bounds["ge"] = item.ge
            if hasattr(item, "le"):
                bounds["le"] = item.le
        assert bounds == {"ge": 1, "le": 100}, bounds


# ---------------------------------------------------------------------------
# LineageResponse / LineageVersion shape
# ---------------------------------------------------------------------------


class TestLineageModels:
    LINEAGE_VERSION_FIELDS = (
        "version_id",
        "version_number",
        "parents",
        "evolution_meta",
        "change_summary",
        "author",
        "created_at",
        "depth",
    )
    LINEAGE_RESPONSE_FIELDS = (
        "entity_id",
        "root_version_id",
        "versions",
        "max_depth_reached",
    )

    def test_doc_lists_lineage_version_fields(self, doc_text):
        for field in self.LINEAGE_VERSION_FIELDS:
            assert f"`{field}`" in doc_text, field

    def test_doc_lists_lineage_response_fields(self, doc_text):
        for field in self.LINEAGE_RESPONSE_FIELDS:
            assert f"`{field}`" in doc_text, field

    def test_lineage_models_match_doc(self):
        from app.models.responses import LineageResponse, LineageVersion

        assert set(self.LINEAGE_VERSION_FIELDS) <= set(LineageVersion.model_fields)
        assert set(self.LINEAGE_RESPONSE_FIELDS) <= set(LineageResponse.model_fields)

    def test_client_lineage_models_mirror_server(self):
        sys.path.insert(0, str(REPO_ROOT / "client" / "python" / "src"))
        from app.models.responses import LineageResponse as ServerLR
        from app.models.responses import LineageVersion as ServerLV
        from gigaevo_client.models import LineageResponse as ClientLR
        from gigaevo_client.models import LineageVersion as ClientLV

        assert set(ServerLV.model_fields) == set(ClientLV.model_fields)
        assert set(ServerLR.model_fields) == set(ClientLR.model_fields)


# ---------------------------------------------------------------------------
# Storage references
# ---------------------------------------------------------------------------


class TestStorageReferences:
    def test_jsonb_column_named(self, doc_text):
        assert "entity_versions.evolution_meta" in doc_text
        assert "JSONB" in doc_text

    def test_parents_column_named(self, doc_text):
        assert "entity_versions.parents" in doc_text
        assert "UUID[]" in doc_text

    def test_columns_exist_on_orm(self):
        from app.db.models import EntityVersion

        assert hasattr(EntityVersion, "evolution_meta")
        assert hasattr(EntityVersion, "parents")
