"""Doc-drift guard for ``docs/CARE_INTEGRATION.md`` (TODO §9 P2).

Pins the umbrella CARE contract doc against the live source of truth:

  * Entity-type allowlist (`VALID_ENTITY_TYPES`).
  * Scope vocabulary + role bundles (`api/app/auth.py`).
  * Namespace-resolution helpers (`default_namespace_for`,
    `default_read_namespace_for`).
  * Library-metadata column inventory + the typed routers that mutate
    them.
  * `event_type` literals emitted by `publish_entity_event` call sites.
  * SSE filter knobs on `/v1/events/stream`.
  * Cross-references to the three sibling docs.

Structural facts only — no prose pinning.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOC_PATH = REPO_ROOT / "docs" / "CARE_INTEGRATION.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.is_file(), f"Doc missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Entity-type allowlist
# ---------------------------------------------------------------------------


class TestEntityTypes:
    EXPECTED_PAIRS = (
        ("step", "/v1/steps"),
        ("chain", "/v1/chains"),
        ("agent", "/v1/agents"),
        ("agent_skill", "/v1/agent-skills"),
        ("memory_card", "/v1/memory-cards"),
    )

    def test_all_singular_names_documented(self, doc_text):
        for singular, _ in self.EXPECTED_PAIRS:
            assert f"`{singular}`" in doc_text, singular

    def test_all_route_prefixes_documented(self, doc_text):
        for _, prefix in self.EXPECTED_PAIRS:
            assert f"`{prefix}`" in doc_text, prefix

    def test_pairs_match_valid_entity_types(self):
        from app.services.entity_service import VALID_ENTITY_TYPES

        # VALID_ENTITY_TYPES is plural→singular.
        plural_to_singular = dict(VALID_ENTITY_TYPES)
        doc_singulars = {s for s, _ in self.EXPECTED_PAIRS}
        live_singulars = set(plural_to_singular.values())
        assert doc_singulars == live_singulars, (
            f"doc-only: {doc_singulars - live_singulars}, "
            f"live-only: {live_singulars - doc_singulars}"
        )


# ---------------------------------------------------------------------------
# Scope vocabulary
# ---------------------------------------------------------------------------


class TestScopes:
    SCOPES = (
        "read:any",
        "write:any",
        "delete:any",
        "clear:all",
        "admin:keys",
        "evolve",
    )

    def test_all_scopes_documented(self, doc_text):
        for scope in self.SCOPES:
            assert f"`{scope}`" in doc_text, scope

    def test_scope_set_matches_auth_module(self):
        from app.auth import ALL_SCOPES

        assert ALL_SCOPES == frozenset(self.SCOPES)

    def test_role_bundles_documented(self, doc_text):
        for role in ("ROLE_READER", "ROLE_EDITOR", "ROLE_ADMIN"):
            assert role in doc_text, role

    def test_role_bundles_exist(self):
        from app.auth import ROLE_ADMIN, ROLE_EDITOR, ROLE_READER

        assert ROLE_READER == frozenset({"read:any"})
        assert ROLE_EDITOR == frozenset({"read:any", "write:any"})
        # ROLE_ADMIN == every scope; equality checked against the live set.
        from app.auth import ALL_SCOPES

        assert ROLE_ADMIN == ALL_SCOPES


# ---------------------------------------------------------------------------
# Namespace resolution
# ---------------------------------------------------------------------------


class TestNamespaceResolution:
    def test_helpers_named_in_doc(self, doc_text):
        # The doc must point readers at the canonical helpers.
        assert "default_namespace_for" in doc_text
        assert "default_read_namespace_for" in doc_text

    def test_helpers_exist(self):
        from app.auth import default_namespace_for, default_read_namespace_for

        assert callable(default_namespace_for)
        assert callable(default_read_namespace_for)

    def test_dual_mode_settings_documented(self, doc_text):
        # The doc must mention the env-flag controlling dual-mode auth.
        assert "AUTH_REQUIRED" in doc_text

    def test_dual_mode_setting_exists(self):
        from app.config import settings

        assert hasattr(settings, "auth_required")


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


class TestChannels:
    def test_canonical_channels_documented(self, doc_text):
        for ch in ("latest", "stable", "evolved"):
            assert f"`{ch}`" in doc_text, ch

    def test_evolved_cross_reference(self, doc_text):
        # The doc must cross-ref the EVOLUTION_META.md spec for the
        # auto-promotion rules.
        assert "EVOLUTION_META.md" in doc_text


# ---------------------------------------------------------------------------
# Library metadata
# ---------------------------------------------------------------------------


class TestLibraryMetadata:
    COLUMNS = ("favourite", "run_count", "last_run_at", "display_name", "description")

    def test_columns_documented(self, doc_text):
        for col in self.COLUMNS:
            assert f"`{col}`" in doc_text, col

    def test_columns_match_orm(self):
        from app.db.models import Entity

        for col in self.COLUMNS:
            assert hasattr(Entity, col), col

    def test_mutator_endpoints_documented(self, doc_text):
        for path in ("POST /favourite", "POST /run-recorded", "PATCH"):
            assert path in doc_text, path


# ---------------------------------------------------------------------------
# List query knobs
# ---------------------------------------------------------------------------


class TestListKnobs:
    KNOBS = (
        "sort_by",
        "sort_dir",
        "favourites_only",
        "tags",
        "q",
        "namespace",
        "limit",
        "offset",
        "cursor",
    )

    def test_all_knobs_documented(self, doc_text):
        for knob in self.KNOBS:
            assert f"`{knob}`" in doc_text, knob

    def test_default_sort_called_out(self, doc_text):
        # The CARE home view defaults — these must surface so callers
        # know what they get when they omit the sort params.
        assert "`last_run_at`" in doc_text
        assert "`desc`" in doc_text


# ---------------------------------------------------------------------------
# Event firehose
# ---------------------------------------------------------------------------


class TestEvents:
    EVENT_TYPES = (
        "created",
        "updated",
        "deleted",
        "pinned",
        "promoted",
        "favourite_toggled",
        "run_recorded",
        "metadata_updated",
    )

    def test_all_event_types_documented(self, doc_text):
        for et in self.EVENT_TYPES:
            assert f"`{et}`" in doc_text, et

    def test_emitted_event_types_match_doc(self):
        """Every event_type literal passed to publish_entity_event in
        the service must be documented."""
        svc_path = REPO_ROOT / "api" / "app" / "services" / "entity_service.py"
        src = svc_path.read_text(encoding="utf-8")
        # Find positional string args to publish_entity_event(…).
        # Pattern: publish_entity_event( <whitespace> "event_type"
        pattern = re.compile(
            r'publish_entity_event\(\s*\n?\s*"([a-z_]+)"',
            re.MULTILINE,
        )
        live_types = set(pattern.findall(src))
        # We expect the documented set is a superset of what live code emits.
        missing = live_types - set(self.EVENT_TYPES)
        assert not missing, f"Live code emits event_types not documented: {missing}"

    def test_sse_filters_documented(self, doc_text):
        for filt in ("entity_type", "entity_id", "namespace", "tags", "event_type"):
            assert f"`?{filt}`" in doc_text or f"`{filt}`" in doc_text, filt

    def test_sse_endpoint_path_documented(self, doc_text):
        assert "/v1/events/stream" in doc_text

    def test_sse_endpoint_registered(self):
        """The events router declares ``/events/stream`` and is mounted
        at ``prefix="/v1"`` in ``main.py``. Confirm the path lands at
        the documented public URL on the actual FastAPI app."""
        from app.main import app

        public_paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
        assert "/v1/events/stream" in public_paths, sorted(public_paths)

    def test_lag_settings_documented(self, doc_text):
        assert "SSE_WARN_LAG_SECONDS" in doc_text
        assert "SSE_DROP_LAG_SECONDS" in doc_text

    def test_lag_settings_exist(self):
        from app.config import settings

        assert hasattr(settings, "sse_warn_lag_seconds")
        assert hasattr(settings, "sse_drop_lag_seconds")


# ---------------------------------------------------------------------------
# Cross-references to sibling docs
# ---------------------------------------------------------------------------


class TestCrossReferences:
    SIBLING_DOCS = (
        "AGENT_SKILL_ENTITY.md",
        "EVOLUTION_META.md",
        "CHAIN_CONTENT_CONVENTIONS.md",
    )

    def test_all_sibling_docs_referenced(self, doc_text):
        for doc in self.SIBLING_DOCS:
            assert doc in doc_text, doc

    def test_sibling_docs_exist(self):
        docs_dir = REPO_ROOT / "docs"
        for doc in self.SIBLING_DOCS:
            assert (docs_dir / doc).is_file(), doc

    def test_chain_metadata_helper_named(self, doc_text):
        # CARE depends on this helper to merge metadata into chain content.
        assert "CareChainMetadata" in doc_text

    def test_chain_metadata_helper_exists(self):
        from app.models.requests import CareChainMetadata

        assert hasattr(CareChainMetadata, "merge_into_content")
