"""Semantic deduplication router (TODO §4 P3).

Surfaces ``GET /v1/{entity_type}/duplicates`` — finds near-duplicate
pairs within a typed entity collection by cosine similarity over the
channel-resolved embedding. CARE / MAGE use this for catalogue
hygiene: surface chains or skills that drift toward each other so a
human can merge them.

The endpoint is gated by ``settings.enable_vector_search`` — without
vector search there are no embeddings to compare. Returns 503 in
that case so callers can fall back gracefully.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db
from ..models.responses import DuplicatesResponse
from ..services.entity_service import VALID_ENTITY_TYPES, EntityService

router = APIRouter()


@router.get(
    "/{entity_type}/duplicates",
    response_model=DuplicatesResponse,
    tags=["search"],
)
async def find_duplicates(
    entity_type: str,
    channel: str = Query(
        "latest",
        description="Channel pointer to resolve each entity to one specific embedding.",
    ),
    threshold: float = Query(
        0.95,
        ge=0.5,
        le=1.0,
        description=(
            "Minimum cosine similarity (inclusive) for a pair to qualify "
            "as a near-duplicate. The TODO §4 spec calls out 0.95 as the "
            "default; loosen it to 0.85 for "
            "exploratory inspection."
        ),
    ),
    namespace: str | None = Query(
        None,
        description=(
            "Restrict the scan to one namespace. Omit to scan every "
            "entity of this type (useful for operator-level hygiene)."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=500,
        description="Maximum number of pairs returned.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Find near-duplicate pairs of a typed entity by cosine similarity.

    Pairs are canonicalised (``entity_a.entity_id < entity_b.entity_id``)
    so each unordered pair appears at most once. Sorted by descending
    similarity so the strongest merge candidates come first.

    * ``400`` when ``entity_type`` is not in ``VALID_ENTITY_TYPES``.
    * ``503`` when the deployment has vector search disabled.
    """
    # Accept both hyphenated and underscored plurals (matches the
    # convention the version router uses).
    normalised = entity_type.replace("-", "_")
    singular = VALID_ENTITY_TYPES.get(normalised)
    if singular is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid entity type {entity_type!r}. "
                f"Must be one of: {sorted(VALID_ENTITY_TYPES)}."
            ),
        )

    svc = EntityService(db)
    data = await svc.find_duplicate_pairs(
        singular,
        channel=channel,
        threshold=threshold,
        namespace=namespace,
        limit=limit,
    )
    if data is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Semantic deduplication requires vector search "
                "(`ENABLE_VECTOR_SEARCH=true`). Enable it on the API "
                "deployment and ensure entities have embeddings."
            ),
        )
    return DuplicatesResponse.model_validate(data)
