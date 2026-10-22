"""Tests for the standardised ``EvolutionMeta`` schema (§5 P1).

The two concentric shapes (CARE/Platform fields + legacy gigaevo-core
fields) are both optional; an empty instance is legal. Pre-existing
rows decoded from JSONB still parse cleanly.
"""

import pytest
from pydantic import ValidationError

from app.models.requests import (
    EntityCreateRequest,
    EntityMeta,
    EvolutionMeta,
)


class TestEvolutionMetaStandardisedShape:
    """The new §5 P1 fields validate and round-trip."""

    def test_empty_is_valid(self):
        m = EvolutionMeta()
        # Every field is optional with default None — empty is legal.
        assert m.parent_version_ids is None
        assert m.fitness_score is None
        assert m.generation is None
        assert m.experiment_id is None
        assert m.objectives is None
        assert m.mutation_kind is None

    def test_full_standardised_payload(self):
        m = EvolutionMeta(
            parent_version_ids=[
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
            ],
            fitness_score=0.87,
            generation=12,
            experiment_id="exp-fin-2026",
            objectives={"accuracy": 0.91, "latency_ms": 1240, "tokens": 4200},
            mutation_kind="crossover",
        )
        assert len(m.parent_version_ids) == 2
        assert m.fitness_score == 0.87
        assert m.generation == 12
        assert m.experiment_id == "exp-fin-2026"
        assert m.objectives["accuracy"] == 0.91
        assert m.mutation_kind == "crossover"

    @pytest.mark.parametrize(
        "kind",
        ["step_swap", "prompt_rewrite", "topology_change", "crossover", "manual_edit", "custom-x"],
    )
    def test_mutation_kind_free_string(self, kind):
        """Free string — typical values listed in docstring, but any value accepted."""
        m = EvolutionMeta(mutation_kind=kind)
        assert m.mutation_kind == kind

    def test_generation_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            EvolutionMeta(generation=-1)


class TestBackwardCompatibility:
    """Legacy gigaevo-core fields still work."""

    def test_legacy_fields_round_trip(self):
        m = EvolutionMeta(
            prompt_ref="prompts/v3.json",
            fitness=0.5,
            is_valid=True,
            metrics={"foo": 0.1},
            behavioral_descriptors={"depth": 3},
        )
        assert m.prompt_ref == "prompts/v3.json"
        assert m.fitness == 0.5
        assert m.is_valid is True
        assert m.metrics == {"foo": 0.1}
        assert m.behavioral_descriptors == {"depth": 3}

    def test_legacy_only_dump_excludes_new_fields_when_unset(self):
        """`model_dump(exclude_none=True)` omits unset CARE fields."""
        m = EvolutionMeta(fitness=0.5, mutation_kind="step_swap")
        dumped = m.model_dump(exclude_none=True)
        assert dumped == {"fitness": 0.5, "mutation_kind": "step_swap"}
        # The new-shape keys are absent because they're None.
        for k in ("parent_version_ids", "fitness_score", "generation",
                  "experiment_id", "objectives"):
            assert k not in dumped

    def test_pre_existing_jsonb_payload_decodes(self):
        """Simulate a row written by gigaevo-core before standardisation."""
        legacy = {
            "mutation_kind": "step_swap",
            "fitness": 0.71,
            "is_valid": True,
            "metrics": {"step_count": 5},
        }
        m = EvolutionMeta.model_validate(legacy)
        assert m.fitness == 0.71
        assert m.is_valid is True
        # New fields default to None.
        assert m.fitness_score is None
        assert m.parent_version_ids is None


class TestMixedNewAndLegacy:
    """`fitness_score` (new) and `fitness` (legacy) can coexist on the same row.

    Some clients may set both during transition; both should round-trip.
    """

    def test_both_fields_set(self):
        m = EvolutionMeta(fitness=0.71, fitness_score=0.87)
        assert m.fitness == 0.71
        assert m.fitness_score == 0.87


class TestEntityCreateRequestRoundTrip:
    """`evolution_meta` flows through the create-request envelope."""

    def test_create_request_with_standardised_evolution_meta(self):
        meta = EvolutionMeta(
            parent_version_ids=["00000000-0000-0000-0000-000000000001"],
            fitness_score=0.92,
            generation=5,
            experiment_id="exp-1",
            objectives={"accuracy": 0.95},
            mutation_kind="prompt_rewrite",
        )
        req = EntityCreateRequest(
            meta=EntityMeta(name="x"),
            content={"version": "1.1", "steps": [{"number": 1}]},
            evolution_meta=meta,
        )
        # `model_dump` of the request preserves the typed sub-model.
        dumped = req.model_dump(exclude_none=True)
        assert dumped["evolution_meta"]["fitness_score"] == 0.92
        assert dumped["evolution_meta"]["objectives"] == {"accuracy": 0.95}

    def test_create_request_accepts_raw_dict_evolution_meta(self):
        """Pydantic coerces a dict on the wire into the typed model."""
        req = EntityCreateRequest(
            meta=EntityMeta(name="x"),
            content={"version": "1.1", "steps": [{"number": 1}]},
            evolution_meta={"fitness_score": 0.5, "generation": 2},
        )
        assert isinstance(req.evolution_meta, EvolutionMeta)
        assert req.evolution_meta.fitness_score == 0.5
        assert req.evolution_meta.generation == 2

    def test_openapi_exposes_new_fields(self):
        from app.main import app

        schema = app.openapi()["components"]["schemas"]["EvolutionMeta"]
        properties = schema["properties"]
        for field in (
            "parent_version_ids",
            "fitness_score",
            "generation",
            "experiment_id",
            "objectives",
            "mutation_kind",
        ):
            assert field in properties, f"Missing {field} on EvolutionMeta OpenAPI schema"

    def test_openapi_preserves_legacy_fields(self):
        from app.main import app

        schema = app.openapi()["components"]["schemas"]["EvolutionMeta"]
        properties = schema["properties"]
        for field in ("prompt_ref", "fitness", "is_valid", "metrics", "behavioral_descriptors"):
            assert field in properties, f"Legacy field {field} disappeared from OpenAPI"
