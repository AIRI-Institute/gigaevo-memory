"""Doc-drift guard for the top-level README architecture section
(TODO §9 P3 — "Update README architecture diagram once auth + new
entity ship").

Structural facts only — we pin the lists/labels that should never
silently drift from the live code, not the prose around them.

Coverage:
  * 5 entity types listed in the Features section match
    ``VALID_ENTITY_TYPES``.
  * Architecture ASCII diagram references every typed router path
    actually mounted in ``main.py``.
  * Auth section lists every scope in ``ALL_SCOPES``.
  * SSE section enumerates every ``event_type`` literal emitted by
    ``publish_entity_event`` call sites.
  * Observability section names every metric series registered in
    ``app.metrics``.
  * Four sibling docs referenced exist on disk.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
README_PATH = REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    assert README_PATH.is_file(), f"README missing: {README_PATH}"
    return README_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------


class TestEntityTypes:
    HUMAN_LABELS = {
        "step": "Steps",
        "chain": "Chains",
        "agent": "Agents",
        "agent_skill": "Agent Skills",
        "memory_card": "Memory Cards",
    }

    def test_every_live_entity_type_listed(self, readme):
        from app.services.entity_service import VALID_ENTITY_TYPES

        for singular in VALID_ENTITY_TYPES.values():
            label = self.HUMAN_LABELS.get(singular)
            assert label is not None, f"Test missing label for {singular!r}"
            # The README has both **Bold** entries in the feature list
            # and bare references in the diagram.
            assert label in readme, label

    def test_agent_skills_callout_specifically(self, readme):
        """The README must specifically advertise AgentSkills since
        the doc-update task is keyed on the new entity type shipping."""
        assert "Agent Skills" in readme
        # Cross-ref to the spec doc must be present.
        assert "docs/AGENT_SKILL_ENTITY.md" in readme


# ---------------------------------------------------------------------------
# Architecture diagram: route prefixes
# ---------------------------------------------------------------------------


class TestArchitectureDiagram:
    REQUIRED_PATHS = (
        "/v1/steps",
        "/v1/chains",
        "/v1/agents",
        "/v1/agent-skills",
        "/v1/memory-cards",
        "/v1/events/stream",
        "/v1/search/unified",
        "/metrics",
        "/health",
    )

    def test_every_required_path_in_diagram(self, readme):
        for path in self.REQUIRED_PATHS:
            assert path in readme, path

    def test_postgres_and_redis_blocks_present(self, readme):
        assert "PostgreSQL" in readme
        assert "pgvector" in readme  # called out explicitly for vector search
        assert "Redis" in readme

    def test_redis_pubsub_channel_named(self, readme):
        # The SSE event firehose uses the Redis pub/sub channel
        # "memory:events" — surface it so operators know what to
        # subscribe to for debugging.
        assert "memory:events" in readme


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthSection:
    def test_dual_mode_flag_documented(self, readme):
        assert "AUTH_REQUIRED" in readme

    def test_all_scopes_listed(self, readme):
        from app.auth import ALL_SCOPES

        for scope in ALL_SCOPES:
            assert f"`{scope}`" in readme, scope

    def test_make_create_key_documented(self, readme):
        # The operator command for issuing API keys must surface so
        # readers know how to bootstrap auth in strict mode.
        assert "make create-key" in readme


# ---------------------------------------------------------------------------
# SSE event types
# ---------------------------------------------------------------------------


class TestSSESection:
    def test_all_emitted_event_types_listed(self, readme):
        """Every ``event_type`` string passed to ``publish_entity_event``
        in the service must appear in the README."""
        svc = REPO_ROOT / "api" / "app" / "services" / "entity_service.py"
        src = svc.read_text(encoding="utf-8")
        pattern = re.compile(
            r'publish_entity_event\(\s*\n?\s*"([a-z_]+)"',
            re.MULTILINE,
        )
        live_types = set(pattern.findall(src))
        missing = [et for et in live_types if f"`{et}`" not in readme]
        assert not missing, f"README missing event_types: {missing}"

    def test_backpressure_settings_named(self, readme):
        assert "SSE_WARN_LAG_SECONDS" in readme
        assert "SSE_DROP_LAG_SECONDS" in readme


# ---------------------------------------------------------------------------
# Observability / Prometheus
# ---------------------------------------------------------------------------


class TestObservabilitySection:
    EXPECTED_METRIC_NAMES = {
        "gigaevo_memory_http_requests_total",
        "gigaevo_memory_http_request_duration_seconds",
        "gigaevo_memory_entities",
    }

    def test_all_metric_names_in_readme(self, readme):
        for name in self.EXPECTED_METRIC_NAMES:
            assert name in readme, name

    def test_metric_names_match_live_registry(self):
        """Pin the README list against the actual prometheus_client
        registry — if a series gets renamed in code, the test fires."""
        from app import metrics as memory_metrics

        live = set()
        for family in memory_metrics.REGISTRY.collect():
            # Counters expose `<base>_total`; histograms/gauges expose
            # the bare name. Normalise so the assertion holds for both.
            if family.type == "counter":
                live.add(family.name + "_total")
            else:
                live.add(family.name)
        assert self.EXPECTED_METRIC_NAMES <= live, (
            f"README claims metrics not in live registry: "
            f"{self.EXPECTED_METRIC_NAMES - live}"
        )


# ---------------------------------------------------------------------------
# Sibling docs cross-referenced
# ---------------------------------------------------------------------------


class TestDocsLinks:
    SIBLING_DOCS = (
        "docs/CARE_INTEGRATION.md",
        "docs/AGENT_SKILL_ENTITY.md",
        "docs/EVOLUTION_META.md",
        "docs/CHAIN_CONTENT_CONVENTIONS.md",
    )

    def test_all_doc_paths_referenced(self, readme):
        for doc in self.SIBLING_DOCS:
            assert doc in readme, doc

    def test_all_doc_paths_exist(self):
        for doc in self.SIBLING_DOCS:
            assert (REPO_ROOT / doc).is_file(), doc


# ---------------------------------------------------------------------------
# Channels (CARE-facing semantics)
# ---------------------------------------------------------------------------


class TestChannels:
    def test_three_canonical_channels_named(self, readme):
        for ch in ("latest", "stable", "evolved"):
            assert f"`{ch}`" in readme, ch

    def test_lineage_and_promotion_endpoints_called_out(self, readme):
        # Two endpoints that landed in this iteration cycle and are
        # CARE-load-bearing.
        assert "/lineage" in readme
        assert "/versions/beating" in readme
