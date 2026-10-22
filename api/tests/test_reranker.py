"""Tests for the reranker hook (P2 §4)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.requests import SearchType
from app.services.search_strategies.base import SearchHit
from app.services.search_strategies.reranker import (
    IdentityReranker,
    RerankerRegistry,
)
from app.services.unified_search_service import UnifiedSearchService


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _hit(entity_id: str, score: float, name: str | None = None) -> SearchHit:
    return SearchHit(
        entity_id=entity_id,
        entity_type="agent_skill",
        name=name or entity_id,
        score=score,
        channel="latest",
        version_id="v1",
        tags=[],
        when_to_use=None,
        content=None,
        document_id=None,
        document_kind=None,
        snippet=None,
    )


class _ReverseReranker:
    """Test fake: reverses the input order so we can assert the hook fired."""

    async def rerank(self, query, hits):
        return list(reversed(hits))


class _SyncReranker:
    """Test fake: synchronous rerank (allowed per the duck-typed contract)."""

    def rerank(self, query, hits):
        return [_hit(h.entity_id, h.score + 100.0) for h in hits]


class _DropZeroReranker:
    """Test fake: drops hits scoring 0."""

    async def rerank(self, query, hits):
        return [h for h in hits if h.score > 0]


@pytest.fixture(autouse=True)
def _restore_registry():
    """Per-test isolation: snapshot registered kinds + restore after."""
    snapshot = dict(RerankerRegistry._factories)
    yield
    RerankerRegistry._factories = snapshot


# ---------------------------------------------------------------------------
# IdentityReranker
# ---------------------------------------------------------------------------


class TestIdentityReranker:
    @pytest.mark.asyncio
    async def test_passes_hits_through_unchanged(self):
        hits = [_hit("a", 1.0), _hit("b", 2.0), _hit("c", 3.0)]
        out = await IdentityReranker().rerank("any-query", hits)
        assert out is hits or out == hits  # may return same object or copy

    @pytest.mark.asyncio
    async def test_empty_list(self):
        assert await IdentityReranker().rerank(None, []) == []


# ---------------------------------------------------------------------------
# RerankerRegistry
# ---------------------------------------------------------------------------


class TestRerankerRegistry:
    def test_identity_always_registered(self):
        assert "identity" in RerankerRegistry.registered_kinds()
        r = RerankerRegistry.get("identity")
        assert isinstance(r, IdentityReranker)

    def test_register_and_get(self):
        RerankerRegistry.register("reverse", _ReverseReranker)
        assert "reverse" in RerankerRegistry.registered_kinds()
        r = RerankerRegistry.get("reverse")
        assert isinstance(r, _ReverseReranker)

    def test_unknown_kind_falls_back_to_identity(self, caplog):
        with caplog.at_level("WARNING"):
            r = RerankerRegistry.get("totally-made-up")
        assert isinstance(r, IdentityReranker)
        # Logs a warning to surface the typo.
        assert any("Unknown reranker_kind" in rec.message for rec in caplog.records)

    def test_unknown_identity_kind_does_not_warn(self, caplog):
        """Explicitly asking for `identity` is silent."""
        with caplog.at_level("WARNING"):
            r = RerankerRegistry.get("identity")
        assert isinstance(r, IdentityReranker)
        assert not [r for r in caplog.records if "Unknown" in r.message]

    def test_register_last_writer_wins(self):
        RerankerRegistry.register("custom", _ReverseReranker)
        RerankerRegistry.register("custom", _SyncReranker)
        r = RerankerRegistry.get("custom")
        assert isinstance(r, _SyncReranker)

    def test_registered_kinds_sorted(self):
        RerankerRegistry.register("z-reranker", IdentityReranker)
        RerankerRegistry.register("a-reranker", IdentityReranker)
        kinds = RerankerRegistry.registered_kinds()
        assert kinds == sorted(kinds)


# ---------------------------------------------------------------------------
# UnifiedSearchService wiring
# ---------------------------------------------------------------------------


def _patch_strategy(hits: list[SearchHit]):
    """Patch every strategy in the service to return the canned hits."""
    async def _fake(self, request):
        return hits

    from app.services.search_strategies.bm25_strategy import BM25SearchStrategy
    from app.services.search_strategies.vector_strategy import VectorSearchStrategy
    from app.services.search_strategies.hybrid_strategy import HybridSearchStrategy

    return [
        patch.object(BM25SearchStrategy, "search", new=_fake),
        patch.object(VectorSearchStrategy, "search", new=_fake),
        patch.object(HybridSearchStrategy, "search", new=_fake),
    ]


@pytest.fixture
def hits():
    return [_hit("a", 1.0), _hit("b", 2.0), _hit("c", 3.0)]


class TestUnifiedSearchServiceWiring:
    @pytest.mark.asyncio
    async def test_default_reranker_is_identity_via_settings(self, hits):
        # Default settings: reranker_kind=="identity".
        svc = UnifiedSearchService(db=AsyncMock())
        assert isinstance(svc._reranker, IdentityReranker)

    @pytest.mark.asyncio
    async def test_settings_kind_drives_reranker_choice(self, monkeypatch):
        RerankerRegistry.register("reverse", _ReverseReranker)
        from app.services import unified_search_service as uss
        monkeypatch.setattr(uss.settings, "reranker_kind", "reverse")
        svc = UnifiedSearchService(db=AsyncMock())
        assert isinstance(svc._reranker, _ReverseReranker)

    @pytest.mark.asyncio
    async def test_explicit_reranker_overrides_settings(self, monkeypatch):
        from app.services import unified_search_service as uss
        monkeypatch.setattr(uss.settings, "reranker_kind", "identity")
        svc = UnifiedSearchService(
            db=AsyncMock(), reranker=_ReverseReranker()
        )
        assert isinstance(svc._reranker, _ReverseReranker)

    @pytest.mark.asyncio
    async def test_search_passes_hits_through_reranker(self, hits):
        svc = UnifiedSearchService(db=AsyncMock(), reranker=_ReverseReranker())
        patches = _patch_strategy(hits)
        for p in patches:
            p.start()
        try:
            out = await svc.search(SearchType.BM25, query="x")
        finally:
            for p in patches:
                p.stop()
        # Original score order: a=1, b=2, c=3. After reverse: c, b, a.
        assert [d["entity_id"] for d in out] == ["c", "b", "a"]

    @pytest.mark.asyncio
    async def test_search_handles_sync_reranker(self, hits):
        svc = UnifiedSearchService(db=AsyncMock(), reranker=_SyncReranker())
        patches = _patch_strategy(hits)
        for p in patches:
            p.start()
        try:
            out = await svc.search(SearchType.BM25, query="x")
        finally:
            for p in patches:
                p.stop()
        # The sync fake adds 100 to every score.
        assert [d["score"] for d in out] == [101.0, 102.0, 103.0]

    @pytest.mark.asyncio
    async def test_reranker_can_drop_hits(self, hits):
        hits_with_zero = [_hit("zero", 0.0), _hit("a", 1.0), _hit("b", 2.0)]
        svc = UnifiedSearchService(
            db=AsyncMock(), reranker=_DropZeroReranker()
        )
        patches = _patch_strategy(hits_with_zero)
        for p in patches:
            p.start()
        try:
            out = await svc.search(SearchType.BM25, query="x")
        finally:
            for p in patches:
                p.stop()
        assert [d["entity_id"] for d in out] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_empty_results_skip_reranker(self):
        """Reranker isn't invoked on an empty hit list."""
        called: list[int] = []

        class _Counting:
            async def rerank(self, query, h):
                called.append(1)
                return h

        svc = UnifiedSearchService(db=AsyncMock(), reranker=_Counting())
        patches = _patch_strategy([])
        for p in patches:
            p.start()
        try:
            out = await svc.search(SearchType.BM25, query="x")
        finally:
            for p in patches:
                p.stop()
        assert out == []
        assert called == []  # short-circuited before the reranker call


class TestBatchSearchReranker:
    @pytest.mark.asyncio
    async def test_each_query_reranked_independently(self):
        """Three queries → three independent reranker calls."""
        invocations: list[str | None] = []

        class _RecordingReranker:
            async def rerank(self, query, h):
                invocations.append(query)
                return h

        hits_a = [_hit("a", 1.0)]
        svc = UnifiedSearchService(db=AsyncMock(), reranker=_RecordingReranker())
        patches = _patch_strategy(hits_a)
        for p in patches:
            p.start()
        try:
            await svc.batch_search(
                SearchType.BM25,
                queries=["query-1", "query-2", "query-3"],
            )
        finally:
            for p in patches:
                p.stop()
        # One rerank call per query (skip is only on empty hits — here
        # each query returns the canned non-empty list).
        assert invocations == ["query-1", "query-2", "query-3"]
