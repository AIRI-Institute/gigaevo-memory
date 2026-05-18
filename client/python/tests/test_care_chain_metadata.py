"""Tests for the client-side ``CareChainMetadata`` mirror."""

import hashlib

import pytest
from pydantic import ValidationError

from gigaevo_memory import CareChainMetadata, ContextFileRef


SHA = hashlib.sha256(b"data.csv").hexdigest()


class TestClientMirror:
    def test_imports_from_top_level(self):
        """Both names re-export via the lazy `__getattr__` pattern."""
        assert CareChainMetadata is not None
        assert ContextFileRef is not None

    def test_empty_payload_valid(self):
        m = CareChainMetadata()
        assert m.context_files == []
        assert m.tags == []

    def test_round_trip_through_chain_content(self):
        m = CareChainMetadata(
            task_description="Develop a financier helper.",
            context_files=[
                ContextFileRef(path="data.csv", sha256=SHA, size_bytes=42)
            ],
            generated_by="mage",
            display_name="Financier helper",
            tags=["finance", "favourite"],
        )
        content = m.merge_into_content({"steps": []})
        # The "steps" key from upstream survives.
        assert content["steps"] == []
        # Every CARE field landed under metadata.
        assert content["metadata"]["task_description"] == "Develop a financier helper."
        assert content["metadata"]["generated_by"] == "mage"
        # Round-trip back to the typed model.
        loaded = CareChainMetadata.from_chain_content(content)
        assert loaded == m

    def test_preserves_non_care_metadata_keys(self):
        """gigaevo-core could add its own keys alongside CARE's."""
        existing = {"metadata": {"core_state": "running"}}
        m = CareChainMetadata(task_description="x")
        out = m.merge_into_content(existing)
        assert out["metadata"]["core_state"] == "running"
        assert out["metadata"]["task_description"] == "x"

    def test_sha256_validation(self):
        with pytest.raises(ValidationError):
            ContextFileRef(path="x", sha256="abc", size_bytes=1)

    def test_size_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            ContextFileRef(path="x", sha256=SHA, size_bytes=-5)

    def test_extract_returns_empty_for_old_chain_without_metadata(self):
        """Pre-convention chains shouldn't crash CARE on load."""
        legacy = {"version": "1.0", "steps": []}
        m = CareChainMetadata.from_chain_content(legacy)
        assert m == CareChainMetadata()
