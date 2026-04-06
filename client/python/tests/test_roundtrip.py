"""Round-trip tests for CARL compatibility adapters."""

import pytest
from mmar_carl import ToolStepDescription

from gigaevo_memory._compat import (
    chain_from_content,
    chain_to_content,
    step_from_content,
    step_to_content,
)


def test_chain_roundtrip_basic(sample_chain_dict):
    """Basic chain round-trip preserves core chain fields."""
    chain = chain_from_content(sample_chain_dict)

    assert len(chain.steps) == 4
    assert chain.max_workers == 3
    assert chain.metadata["name"] == "fin_triage_v2"

    restored = chain_to_content(chain)
    assert restored["version"] == "1.1"
    assert restored["max_workers"] == sample_chain_dict["max_workers"]
    assert restored["enable_progress"] == sample_chain_dict["enable_progress"]
    assert restored["metadata"] == sample_chain_dict["metadata"]
    assert len(restored["steps"]) == len(sample_chain_dict["steps"])


def test_chain_step_fields_preserved(sample_chain_dict):
    """Verify core step fields are preserved through round-trip."""
    chain = chain_from_content(sample_chain_dict)
    restored = chain_to_content(chain)

    for orig, rest in zip(sample_chain_dict["steps"], restored["steps"]):
        assert rest["number"] == orig["number"]
        assert rest["title"] == orig["title"]
        assert rest["dependencies"] == orig["dependencies"]
        assert rest.get("step_type", "llm") == orig.get("step_type", "llm")
        if orig.get("step_type", "llm") == "llm":
            assert rest["aim"] == orig["aim"]
            assert rest["reasoning_questions"] == orig["reasoning_questions"]
            assert rest["stage_action"] == orig["stage_action"]
            assert rest["example_reasoning"] == orig["example_reasoning"]
            assert rest["step_context_queries"] == orig["step_context_queries"]
            # llm_config may have additional fields added by CARL (e.g., timeout: None)
            orig_llm_config = orig.get("llm_config") or {}
            rest_llm_config = rest.get("llm_config") or {}
            # Verify all original fields are preserved
            for key, value in orig_llm_config.items():
                assert rest_llm_config.get(key) == value
        else:
            assert rest["step_config"] == orig["step_config"]


def test_chain_dag_validation(sample_chain_dict):
    """Verify DAG validation catches invalid dependencies."""
    # Valid chain should deserialize fine
    chain = chain_from_content(sample_chain_dict)
    assert chain is not None

    # Invalid: step depends on non-existent step
    bad_dict = dict(sample_chain_dict)
    bad_dict["steps"] = [
        {
            "number": 1,
            "title": "Step 1",
            "aim": "Validate dependency constraints",
            "reasoning_questions": "Are dependencies valid?",
            "dependencies": [99],  # Non-existent
            "stage_action": "Try to build a chain with invalid deps",
            "example_reasoning": "This should fail validation",
        }
    ]
    with pytest.raises(ValueError, match="non-existent"):
        chain_from_content(bad_dict)


def test_step_roundtrip(sample_step_dict):
    """Single step round-trip: typed step preserves content."""
    step = step_from_content(sample_step_dict)
    assert isinstance(step, ToolStepDescription)
    assert step.number == 1
    assert step.title == "Fetch Financial Data"

    restored = step_to_content(step)
    assert restored["number"] == sample_step_dict["number"]
    assert restored["title"] == sample_step_dict["title"]
    assert restored["step_type"] == "tool"
    assert restored["step_config"] == sample_step_dict["step_config"]


def test_compat_chain_from_content(sample_chain_dict):
    """Test the _compat adapter for chain deserialization."""
    chain = chain_from_content(sample_chain_dict)
    assert len(chain.steps) == 4

    content = chain_to_content(chain)
    assert content["max_workers"] == 3
    assert len(content["steps"]) == 4


def test_compat_step_from_content(sample_step_dict):
    """Test the _compat adapter for step deserialization."""
    step = step_from_content(sample_step_dict)
    assert isinstance(step, ToolStepDescription)
    assert step.title == "Fetch Financial Data"

    content = step_to_content(step)
    assert content["title"] == "Fetch Financial Data"
    assert content["step_type"] == "tool"
