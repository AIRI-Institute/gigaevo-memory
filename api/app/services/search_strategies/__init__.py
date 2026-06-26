"""Search strategies for unified search.

This package provides a strategy pattern implementation for different
search types (BM25, Vector, Hybrid), allowing easy extensibility.
"""

from .base import SearchStrategy, SearchRequest
from .bm25_strategy import BM25SearchStrategy
from .vector_strategy import VectorSearchStrategy
from .hybrid_strategy import HybridSearchStrategy

__all__ = [
    "SearchStrategy",
    "SearchRequest",
    "BM25SearchStrategy",
    "VectorSearchStrategy",
    "HybridSearchStrategy",
]
