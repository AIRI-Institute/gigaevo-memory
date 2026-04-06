"""Embeddings endpoint for server-side text embedding."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..config import settings
from ..services.embedding_service import EmbeddingService

router = APIRouter()


class EmbeddingsRequest(BaseModel):
    """Request for text embeddings."""

    texts: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of text strings to embed",
    )
    model: str | None = Field(
        default=None,
        description="Optional override of the default model",
    )


class EmbeddingsResponse(BaseModel):
    """Response with text embeddings."""

    embeddings: list[list[float]] = Field(
        description="List of embedding vectors, one per input text"
    )
    model: str = Field(description="Model name used for embedding")
    dimension: int = Field(description="Dimension of embedding vectors")


@router.post("/embeddings", response_model=EmbeddingsResponse)
async def create_embeddings(
    request: EmbeddingsRequest,
) -> EmbeddingsResponse:
    """Generate embeddings for text inputs.

    This endpoint uses the configured embedding provider to generate
    vector embeddings for the input texts. Supports batch processing
    for efficiency.

    Example request:
        {
            "texts": ["Hello world", "Search query"],
            "model": "all-MiniLM-L6-v2"  // optional
        }

    Example response:
        {
            "embeddings": [[0.1, 0.2, ...], [0.3, 0.4, ...]],
            "model": "all-MiniLM-L6-v2",
            "dimension": 384
        }

    Raises:
        503: If embedding service is not available
    """
    if not settings.enable_vector_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector search is not enabled. Set ENABLE_VECTOR_SEARCH=true.",
        )

    try:
        # Get or create embedding service
        embedding_service = await EmbeddingService.create()

        # Generate embeddings
        embeddings = await embedding_service.embed_batch(request.texts)

        return EmbeddingsResponse(
            embeddings=embeddings,
            model=request.model or settings.embedding_model,
            dimension=embedding_service.dimension,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(exc)}",
        ) from exc
