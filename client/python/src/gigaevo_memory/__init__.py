"""GigaEvo Memory Module Python client library."""

from __future__ import annotations

__version__ = "0.2.3"

__all__ = [
    "MemoryClient",
    "PlatformMemoryClient",
    "SearchType",
    "CachePolicy",
    "EntityRef",
    "EntityResponse",
    "VersionInfo",
    "VersionDetail",
    "DiffResponse",
    "FacetsResponse",
    "AgentSpec",
    "MemoryCardExplanation",
    "MemoryCardSpec",
    "SearchHitData",
    "ChainDict",
    "StepDict",
    "AgentDict",
    "MemoryCardDict",
    "EmbeddingProvider",
    "SentenceTransformersProvider",
    "HuggingFaceProvider",
    "OpenAIProvider",
    "MemoryApiProvider",
    "get_default_provider",
    "set_default_provider",
    "MemoryError",
    "NotFoundError",
    "ConflictError",
    "ConnectionError",
    "ValidationError",
]


def __getattr__(name: str):
    if name == "MemoryClient":
        from .client import MemoryClient

        return MemoryClient
    if name == "PlatformMemoryClient":
        from .platform_client import PlatformMemoryClient

        return PlatformMemoryClient
    if name == "SearchType":
        from .search_types import SearchType

        return SearchType
    if name == "CachePolicy":
        from .cache import CachePolicy

        return CachePolicy
    if name in {
        "EmbeddingProvider",
        "SentenceTransformersProvider",
        "HuggingFaceProvider",
        "OpenAIProvider",
        "MemoryApiProvider",
        "get_default_provider",
        "set_default_provider",
    }:
        from . import embeddings as _embeddings

        return getattr(_embeddings, name)
    if name in {
        "MemoryError",
        "NotFoundError",
        "ConflictError",
        "ConnectionError",
        "ValidationError",
    }:
        from . import exceptions as _exceptions

        return getattr(_exceptions, name)
    if name in {
        "AgentDict",
        "AgentSpec",
        "ChainDict",
        "DiffResponse",
        "EntityRef",
        "EntityResponse",
        "FacetsResponse",
        "MemoryCardDict",
        "MemoryCardExplanation",
        "MemoryCardSpec",
        "SearchHitData",
        "StepDict",
        "VersionDetail",
        "VersionInfo",
    }:
        from . import models as _models

        return getattr(_models, name)
    raise AttributeError(f"module 'gigaevo_memory' has no attribute {name!r}")
