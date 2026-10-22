"""Pluggable reranker hook for unified search (P2 §4).

A reranker takes the top-K hits returned by a primary search
strategy (BM25 / vector / hybrid) and applies a second pass — a
cross-encoder model, a learning-to-rank heuristic, or anything else
that improves ordering without changing the candidate set.

The hook is intentionally minimal:

    class Reranker(Protocol):
        async def rerank(
            self, query: str | None, hits: list[SearchHit]
        ) -> list[SearchHit]:
            ...

Implementations may:
    * Re-order ``hits`` (the typical case);
    * Drop hits (e.g. zero-score post-rerank);
    * Update ``score`` to reflect the reranker's scale.

They MUST NOT introduce hits the primary strategy didn't return —
the candidate set is closed at retrieval time.

The registry pattern (``RerankerRegistry``) lets out-of-tree code
plug a new reranker without modifying this file. The default
``IdentityReranker`` is a no-op so unsetting / misconfiguring the
env never breaks search.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol, runtime_checkable

from .base import SearchHit

logger = logging.getLogger(__name__)


@runtime_checkable
class Reranker(Protocol):
    """Two-stage reranker contract."""

    async def rerank(
        self, query: str | None, hits: list[SearchHit]
    ) -> list[SearchHit]:
        """Return a possibly-reordered (and possibly-filtered) list of
        the same SearchHit objects the primary strategy produced.

        ``query`` is the original text query (None for pure vector
        searches when no query string was supplied).
        """
        ...


class IdentityReranker:
    """No-op default. Returns the list verbatim.

    Used when ``settings.reranker_kind == "identity"`` (the default)
    and as a safe fallback when an unknown kind is configured.
    """

    async def rerank(
        self, query: str | None, hits: list[SearchHit]
    ) -> list[SearchHit]:
        return hits


#: A factory takes no args and returns a Reranker instance.
RerankerFactory = Callable[[], "Reranker | Awaitable[Reranker]"]


class RerankerRegistry:
    """Lookup table mapping ``kind`` strings to ``Reranker`` factories.

    Registration is module-import-time: subpackages that ship a
    cross-encoder or other reranker call ``RerankerRegistry.register``
    on import to make their implementation discoverable via
    ``settings.reranker_kind``.
    """

    _factories: dict[str, RerankerFactory] = {}

    @classmethod
    def register(cls, kind: str, factory: RerankerFactory) -> None:
        """Register a factory under ``kind``. Last registration wins
        (so tests can override the default for a single test)."""
        cls._factories[kind] = factory

    @classmethod
    def get(cls, kind: str) -> Reranker:
        """Look up and instantiate the reranker for ``kind``.

        Falls back to :class:`IdentityReranker` (with a warning) when
        the kind isn't registered, so a typo in the env never breaks
        search.
        """
        factory = cls._factories.get(kind)
        if factory is None:
            if kind != "identity":
                logger.warning(
                    "Unknown reranker_kind=%r — falling back to IdentityReranker. "
                    "Registered kinds: %s",
                    kind,
                    sorted(cls._factories),
                )
            return IdentityReranker()
        return factory()  # type: ignore[return-value]

    @classmethod
    def registered_kinds(cls) -> list[str]:
        """Return the sorted list of registered kinds — useful for
        ``/health`` introspection and CLI validation."""
        return sorted(cls._factories)

    @classmethod
    def clear(cls) -> None:
        """Reset the registry to only the built-in identity reranker.
        Test-only — never call from production code."""
        cls._factories = {"identity": IdentityReranker}


# Always-available default.
RerankerRegistry.register("identity", IdentityReranker)
