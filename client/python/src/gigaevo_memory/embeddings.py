"""Embedding providers for vector search.

This module provides a pluggable interface for different embedding providers,
allowing users to choose between SentenceTransformers, HuggingFace, OpenAI,
or custom implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers.

    Implement this interface to add support for custom embedding models
    or external embedding services.

    Example:
        >>> class MyProvider(EmbeddingProvider):
        ...     def embed(self, texts: list[str]) -> list[list[float]]:
        ...         # Your embedding logic here
        ...         return embeddings
        ...     @property
        ...     def dimension(self) -> int:
        ...         return 768
    """

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into vectors.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors, one per input text
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the dimension of embedding vectors."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text.

        Convenience method that wraps embed() for single queries.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        return self.embed([text])[0]


class SentenceTransformersProvider(EmbeddingProvider):
    """Embedding provider using SentenceTransformers library.

    This is the default provider for local embedding generation.
    Model is lazy-loaded on first use.

    Example:
        >>> provider = SentenceTransformersProvider("all-MiniLM-L6-v2")
        >>> embeddings = provider.embed(["text to embed"])
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str | None = None):
        """Initialize the provider.

        Args:
            model_name: Name of the SentenceTransformers model to use
            device: Device to run on (cpu, cuda, etc.). Auto-detected if None.
        """
        self.model_name = model_name
        self.device = device
        self._model: Any = None
        self._dimension: int | None = None

    def _load_model(self) -> Any:
        """Lazy-load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is required for SentenceTransformersProvider. "
                    "Install with: pip install sentence-transformers"
                ) from exc

            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._dimension = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using SentenceTransformers."""
        model = self._load_model()
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        if self._dimension is None:
            self._load_model()
        return self._dimension or 384  # Default for all-MiniLM-L6-v2


class HuggingFaceProvider(EmbeddingProvider):
    """Embedding provider using HuggingFace Inference API.

    Useful for using hosted models without local compute.

    Example:
        >>> provider = HuggingFaceProvider(
        ...     api_key="hf_...",
        ...     model="sentence-transformers/all-MiniLM-L6-v2"
        ... )
        >>> embeddings = provider.embed(["text to embed"])
    """

    def __init__(
        self,
        api_key: str,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384,
        api_url: str = "https://api-inference.huggingface.co",
    ):
        """Initialize the provider.

        Args:
            api_key: HuggingFace API key
            model: Model identifier on HuggingFace
            dimension: Embedding dimension
            api_url: HuggingFace Inference API endpoint
        """
        self.api_key = api_key
        self.model = model
        self._dimension = dimension
        self.api_url = api_url
        self._client = httpx.Client(
            base_url=api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using HuggingFace Inference API."""
        response = self._client.post(
            f"/pipeline/feature-extraction/{self.model}",
            json={"inputs": texts},
        )
        response.raise_for_status()
        result = response.json()

        # Handle different response formats
        if isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], list):
                return result
            elif isinstance(result[0], dict) and "embedding" in result[0]:
                return [item["embedding"] for item in result]
        raise ValueError(f"Unexpected response format from HuggingFace API: {result}")

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class OpenAIProvider(EmbeddingProvider):
    """Embedding provider using OpenAI API.

    Example:
        >>> provider = OpenAIProvider(api_key="sk-...", model="text-embedding-3-small")
        >>> embeddings = provider.embed(["text to embed"])
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        api_url: str = "https://api.openai.com/v1",
    ):
        """Initialize the provider.

        Args:
            api_key: OpenAI API key
            model: OpenAI embedding model to use
            dimension: Embedding dimension
            api_url: OpenAI API endpoint
        """
        self.api_key = api_key
        self.model = model
        self._dimension = dimension
        self.api_url = api_url
        self._client = httpx.Client(
            base_url=api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using OpenAI API."""
        response = self._client.post(
            "/embeddings",
            json={
                "input": texts,
                "model": self.model,
            },
        )
        response.raise_for_status()
        result = response.json()

        # Sort by index to maintain order
        embeddings = sorted(
            result["data"],
            key=lambda x: x["index"],
        )
        return [item["embedding"] for item in embeddings]

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class MemoryApiProvider(EmbeddingProvider):
    """Embedding provider that uses the Memory API's embedding endpoint.

    This is useful when the API server handles embedding generation,
    keeping the client lightweight.

    Example:
        >>> provider = MemoryApiProvider(base_url="http://localhost:8000")
        >>> embeddings = provider.embed(["text to embed"])
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        dimension: int = 384,
    ):
        """Initialize the provider.

        Args:
            base_url: Base URL of the Memory API
            dimension: Expected embedding dimension
        """
        self._dimension = dimension
        self._client = httpx.Client(base_url=base_url, timeout=30.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the Memory API."""
        response = self._client.post(
            "/v1/embeddings",
            json={"texts": texts},
        )
        response.raise_for_status()
        result = response.json()
        return result["embeddings"]

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


# Default provider instance (lazy-loaded)
_default_provider: EmbeddingProvider | None = None


def get_default_provider() -> EmbeddingProvider:
    """Get the default embedding provider.

    Returns a SentenceTransformersProvider with the default model.
    The model is loaded on first use.
    """
    global _default_provider
    if _default_provider is None:
        _default_provider = SentenceTransformersProvider()
    return _default_provider


def set_default_provider(provider: EmbeddingProvider) -> None:
    """Set the default embedding provider globally.

    Args:
        provider: Provider instance to use as default
    """
    global _default_provider
    _default_provider = provider
