"""Shared search enums used by lightweight and full memory clients."""

from __future__ import annotations

from enum import Enum


class SearchType(str, Enum):
    """Search algorithm type."""

    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"
