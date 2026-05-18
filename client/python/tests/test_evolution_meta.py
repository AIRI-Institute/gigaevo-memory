"""Tests for the client-side ``EvolutionMeta`` mirror."""

import pytest
from pydantic import ValidationError

from gigaevo_memory import EvolutionMeta


class TestEvolutionMetaMirror:
    def test_imports_from_top_level(self):
        assert EvolutionMeta is not None

    def test_empty_is_valid(self):
        m = EvolutionMeta()
        assert m.parent_version_ids is None
        assert m.fitness_score is None
        assert m.generation is None

    def test_standardised_fields_round_trip(self):
        m = EvolutionMeta(
            parent_version_ids=["v1"],
            fitness_score=0.87,
            generation=12,
            experiment_id="exp-1",
            objectives={"accuracy": 0.91},
            mutation_kind="crossover",
        )
        dumped = m.model_dump(exclude_none=True)
        assert dumped["fitness_score"] == 0.87
        assert dumped["generation"] == 12
        assert dumped["objectives"] == {"accuracy": 0.91}

    def test_legacy_fields_preserved(self):
        m = EvolutionMeta(
            prompt_ref="p", fitness=0.5, is_valid=True,
            metrics={"a": 1}, behavioral_descriptors={"b": 2},
        )
        assert m.fitness == 0.5
        assert m.is_valid is True

    def test_generation_validation(self):
        with pytest.raises(ValidationError):
            EvolutionMeta(generation=-1)

    def test_jsonb_round_trip(self):
        """A dict pulled from server JSONB validates back to the typed model."""
        from_server = {
            "fitness_score": 0.71,
            "generation": 3,
            "mutation_kind": "step_swap",
            "objectives": {"f1": 0.8},
        }
        m = EvolutionMeta.model_validate(from_server)
        assert m.fitness_score == 0.71
        assert m.objectives == {"f1": 0.8}
