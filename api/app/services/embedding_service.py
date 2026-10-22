"""Server-side embedding service with multiple provider backends.

This module provides a centralized embedding service that supports
multiple providers (SentenceTransformers, OpenAI, HuggingFace) and
can be configured via environment variables.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from ..config import settings


class EmbeddingBackend(ABC):
    """Abstract base class for embedding backends.

    Server-side version of EmbeddingProvider with async support.
    """

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
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

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        result = await self.embed([text])
        return result[0]


class SentenceTransformersBackend(EmbeddingBackend):
    """Embedding backend using SentenceTransformers library.

    This is the default backend for local embedding generation.
    Model is lazy-loaded on first use.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str | None = None):
        """Initialize the backend.

        Args:
            model_name: Name of the SentenceTransformers model to use
            device: Device to run on (cpu, cuda, mps, etc.). Auto-detected if None.
        """
        self.model_name = model_name
        self.device = device
        self._model: Any = None
        self._dimension: int | None = None

    async def _load_model(self) -> Any:
        """Lazy-load the model in a thread pool to avoid blocking."""
        if self._model is None:
            # Run in thread pool to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(None, self._load_model_sync)
        return self._model

    def _load_model_sync(self) -> Any:
        """Synchronous model loading."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for SentenceTransformersBackend. "
                "Install with: pip install sentence-transformers"
            ) from exc

        model = SentenceTransformer(self.model_name, device=self.device)
        self._dimension = model.get_sentence_embedding_dimension()
        return model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using SentenceTransformers."""
        model = await self._load_model()

        # Run encoding in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(texts, convert_to_numpy=True, show_progress_bar=False),
        )

        return [emb.tolist() for emb in embeddings]

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        if self._dimension is None:
            # Trigger model load
            asyncio.create_task(self._load_model())
        return self._dimension or 384  # Default for all-MiniLM-L6-v2


class OpenAIBackend(EmbeddingBackend):
    """Embedding backend using OpenAI API."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        api_url: str = "https://api.openai.com/v1",
    ):
        """Initialize the backend.

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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using OpenAI API."""
        import httpx

        async with httpx.AsyncClient(
            base_url=self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        ) as client:
            response = await client.post(
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


class HuggingFaceBackend(EmbeddingBackend):
    """Embedding backend using HuggingFace Inference API."""

    def __init__(
        self,
        api_key: str,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384,
        api_url: str = "https://api-inference.huggingface.co",
    ):
        """Initialize the backend.

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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using HuggingFace Inference API."""
        import httpx

        async with httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,
        ) as client:
            response = await client.post(
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
            raise ValueError(
                f"Unexpected response format from HuggingFace API: {result}"
            )

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension


class EmbeddingService:
    """Centralized embedding service.

    Provides embedding generation with configured backend and caching.
    """

    _instance: EmbeddingService | None = None

    def __init__(self, backend: EmbeddingBackend):
        """Initialize the embedding service.

        Args:
            backend: Embedding backend to use
        """
        self._backend = backend
        self._cache: dict[str, list[float]] = {}

    @classmethod
    def get_instance(cls) -> EmbeddingService:
        """Get the singleton instance.

        Returns:
            EmbeddingService instance

        Raises:
            ValueError: If service has not been initialized
        """
        if cls._instance is None:
            raise ValueError(
                "EmbeddingService not initialized. Call create() first."
            )
        return cls._instance

    @classmethod
    async def create(cls) -> EmbeddingService:
        """Create and initialize the embedding service.

        Reads configuration from settings and creates appropriate backend.

        Returns:
            Initialized EmbeddingService instance
        """
        if cls._instance is not None:
            return cls._instance

        backend = cls._create_backend()
        cls._instance = cls(backend)
        return cls._instance

    @classmethod
    def _create_backend(cls) -> EmbeddingBackend:
        """Create embedding backend from settings.

        Returns:
            Configured embedding backend

        Raises:
            ValueError: If provider configuration is invalid
        """
        provider_type = settings.embedding_provider.lower()

        if provider_type == "sentencetransformers":
            return SentenceTransformersBackend(
                model_name=settings.embedding_model,
                device=settings.sentencetransformers_device,
            )
        elif provider_type == "openai":
            if not settings.openai_api_key:
                raise ValueError(
                    "OPENAI_API_KEY required for OpenAI provider"
                )
            return OpenAIBackend(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                dimension=settings.embedding_dimension,
            )
        elif provider_type == "huggingface":
            if not settings.huggingface_api_key:
                raise ValueError(
                    "HUGGINGFACE_API_KEY required for HuggingFace provider"
                )
            return HuggingFaceBackend(
                api_key=settings.huggingface_api_key,
                model=settings.embedding_model,
                dimension=settings.embedding_dimension,
            )
        else:
            raise ValueError(f"Unknown embedding provider: {provider_type}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single batch request.

        Uses simple caching for repeated texts.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors, one per input text
        """
        if not texts:
            return []

        # Check cache for each text
        cached_embeddings = {}
        uncached_texts = []
        uncached_indices = []

        for idx, text in enumerate(texts):
            if text in self._cache:
                cached_embeddings[idx] = self._cache[text]
            else:
                uncached_texts.append(text)
                uncached_indices.append(idx)

        # Embed uncached texts in batch
        if uncached_texts:
            new_embeddings = await self._backend.embed(uncached_texts)

            # Cache and combine results
            results = [None] * len(texts)
            for idx, embedding in zip(uncached_indices, new_embeddings):
                self._cache[uncached_texts[uncached_indices.index(idx)]] = embedding
                results[idx] = embedding

            # Fill in cached results
            for idx, embedding in cached_embeddings.items():
                results[idx] = embedding

            return results

        # All cached
        return [cached_embeddings[idx] for idx in range(len(texts))]

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        result = await self.embed_batch([text])
        return result[0]

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._backend.dimension
