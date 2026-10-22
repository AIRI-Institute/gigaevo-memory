"""Tests for the server-side ``CareChainMetadata`` schema.

The convention is documented in ``docs/CHAIN_CONTENT_CONVENTIONS.md``.
Models live in ``api/app/models/requests.py`` (client-side mirror in
``gigaevo_memory.models``).
"""

import hashlib

import pytest
from pydantic import ValidationError

from app.models.requests import CareChainMetadata, ContextFileRef

SHA = hashlib.sha256(b"report.pdf").hexdigest()


class TestContextFileRef:
    def test_minimal_payload(self):
        f = ContextFileRef(path="report.pdf", sha256=SHA, size_bytes=152034)
        assert f.path == "report.pdf"
        assert f.size_bytes == 152034
        assert f.mime_type is None

    def test_with_mime_type(self):
        f = ContextFileRef(
            path="report.pdf",
            sha256=SHA,
            size_bytes=152034,
            mime_type="application/pdf",
        )
        assert f.mime_type == "application/pdf"

    def test_sha256_must_be_64_hex(self):
        with pytest.raises(ValidationError):
            ContextFileRef(path="x", sha256="too-short", size_bytes=1)
        with pytest.raises(ValidationError):
            ContextFileRef(path="x", sha256="z" * 64, size_bytes=1)

    def test_sha256_accepts_uppercase(self):
        f = ContextFileRef(path="x", sha256=SHA.upper(), size_bytes=1)
        assert f.sha256 == SHA.upper()

    def test_size_bytes_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            ContextFileRef(path="x", sha256=SHA, size_bytes=-1)


class TestCareChainMetadataValidation:
    def test_empty_payload_is_valid(self):
        """The whole block is optional; an empty instance is legal."""
        m = CareChainMetadata()
        assert m.task_description is None
        assert m.context_files == []
        assert m.tags == []

    def test_full_payload_round_trip(self):
        payload = {
            "task_description": "Develop a financier helper.",
            "context_files": [
                {"path": "report.pdf", "sha256": SHA, "size_bytes": 152034}
            ],
            "generated_by": "mage",
            "mage_metadata": {"domain": "finance", "num_steps": 5},
            "display_name": "Financier helper",
            "description": "Drafts monthly reports.",
            "tags": ["finance", "favourite"],
        }
        m = CareChainMetadata(**payload)
        # exclude_none=True so optional unset fields aren't echoed back.
        assert m.model_dump(exclude_defaults=False)["task_description"] == "Develop a financier helper."
        assert m.context_files[0].path == "report.pdf"
        assert m.mage_metadata == {"domain": "finance", "num_steps": 5}

    def test_display_name_max_200(self):
        with pytest.raises(ValidationError):
            CareChainMetadata(display_name="x" * 201)


class TestFromChainContent:
    def test_missing_metadata_block_returns_empty(self):
        assert CareChainMetadata.from_chain_content({}) == CareChainMetadata()
        assert CareChainMetadata.from_chain_content({"steps": []}) == CareChainMetadata()

    def test_metadata_block_extracted(self):
        content = {
            "steps": [],
            "metadata": {
                "task_description": "Q1 report",
                "generated_by": "mage",
                "tags": ["q1"],
            },
        }
        m = CareChainMetadata.from_chain_content(content)
        assert m.task_description == "Q1 report"
        assert m.generated_by == "mage"
        assert m.tags == ["q1"]

    def test_ignores_non_convention_keys(self):
        """Other clients may add their own keys — we ignore, not crash."""
        content = {
            "metadata": {
                "task_description": "x",
                "internal_state": {"foo": "bar"},  # not in convention
                "unknown_field": 42,
            }
        }
        m = CareChainMetadata.from_chain_content(content)
        assert m.task_description == "x"

    def test_handles_non_dict_metadata_block(self):
        """If metadata is, say, a list (broken client), don't crash."""
        content = {"metadata": ["bogus"]}
        assert CareChainMetadata.from_chain_content(content) == CareChainMetadata()

    def test_handles_non_dict_content(self):
        # Defensive: shouldn't normally happen, but be robust.
        assert CareChainMetadata.from_chain_content(None) == CareChainMetadata()  # type: ignore[arg-type]


class TestMergeIntoContent:
    def test_merges_into_empty_content(self):
        m = CareChainMetadata(task_description="x", generated_by="mage")
        out = m.merge_into_content({})
        assert out["metadata"]["task_description"] == "x"
        assert out["metadata"]["generated_by"] == "mage"

    def test_preserves_non_care_metadata_keys(self):
        """Other clients' keys in `metadata` survive the merge."""
        existing = {"metadata": {"internal_state": {"foo": "bar"}}, "steps": []}
        m = CareChainMetadata(task_description="x")
        out = m.merge_into_content(existing)
        assert out["metadata"]["internal_state"] == {"foo": "bar"}
        assert out["metadata"]["task_description"] == "x"
        # Outside-metadata keys preserved too.
        assert out["steps"] == []

    def test_overwrites_existing_care_keys(self):
        """When CARE writes a key, it overrides the stored value."""
        existing = {"metadata": {"task_description": "old"}}
        m = CareChainMetadata(task_description="new")
        out = m.merge_into_content(existing)
        assert out["metadata"]["task_description"] == "new"

    def test_returns_new_dict_does_not_mutate_input(self):
        existing = {"metadata": {"task_description": "old"}}
        m = CareChainMetadata(task_description="new")
        m.merge_into_content(existing)
        assert existing["metadata"]["task_description"] == "old"


class TestRoundTrip:
    """End-to-end: build → merge → reload → equality."""

    def test_full_round_trip(self):
        m = CareChainMetadata(
            task_description="Q1 report",
            context_files=[
                ContextFileRef(
                    path="data.csv",
                    sha256=SHA,
                    size_bytes=42,
                    mime_type="text/csv",
                )
            ],
            generated_by="mage",
            display_name="Q1 Reporter",
            tags=["finance"],
        )
        content = m.merge_into_content({"steps": []})
        loaded = CareChainMetadata.from_chain_content(content)
        assert loaded == m
