"""CRUD router for all entity types: steps, chains, agents, memory_cards."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import SCOPE_CLEAR_ALL, AuthContext, require_api_key
from ..db.session import get_db
from ..models.requests import EntityCreateRequest, EntityUpdateRequest
from ..models.responses import EntityResponse
from ..services.entity_service import VALID_ENTITY_TYPES, EntityService, compute_etag

router = APIRouter()


def _validate_type(entity_type: str) -> str:
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity type '{entity_type}'. Must be one of: {list(VALID_ENTITY_TYPES.keys())}",
        )
    return entity_type


@router.post("/{entity_type}", status_code=201, response_model=EntityResponse)
async def create_entity(
    entity_type: str,
    body: EntityCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new entity with its first version."""
    _validate_type(entity_type)
    svc = EntityService(db)

    evolution_meta = body.evolution_meta.model_dump() if body.evolution_meta else None

    try:
        entity, version = await svc.create_entity(
            entity_type_plural=entity_type,
            name=body.meta.name,
            content=body.content,
            embedding=body.embedding,
            tags=body.meta.tags,
            when_to_use=body.meta.when_to_use,
            author=body.meta.author,
            namespace=body.meta.namespace,
            channel=body.channel,
            evolution_meta=evolution_meta,
            parent_version_id=body.parent_version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    etag = compute_etag(version.content_json)
    return EntityResponse(
        entity_type=entity.entity_type,
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        version_number=version.version_number,
        channel=body.channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.get("/{entity_type}/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_type: str,
    entity_id: uuid.UUID,
    channel: str = "latest",
    if_none_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Get an entity by ID, resolving the channel to a specific version."""
    _validate_type(entity_type)
    svc = EntityService(db)
    result = await svc.get_entity(entity_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity, version = result
    etag = compute_etag(version.content_json)

    # Conditional GET: return 304 if content unchanged
    if if_none_match and if_none_match == etag:
        return Response(status_code=304)

    return EntityResponse(
        entity_type=entity.entity_type,
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        version_number=version.version_number,
        channel=channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.put("/{entity_type}/{entity_id}", response_model=EntityResponse)
async def update_entity(
    entity_type: str,
    entity_id: uuid.UUID,
    body: EntityUpdateRequest,
    if_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Update an entity by creating a new immutable version."""
    _validate_type(entity_type)
    svc = EntityService(db)

    # Optimistic concurrency check
    if if_match:
        current = await svc.get_entity(entity_id, body.channel)
        if current is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        current_etag = compute_etag(current[1].content_json)
        if if_match != current_etag:
            raise HTTPException(
                status_code=412, detail="Precondition Failed: ETag mismatch"
            )

    evolution_meta = body.evolution_meta.model_dump() if body.evolution_meta else None

    try:
        result = await svc.update_entity(
            entity_id=entity_id,
            content=body.content,
            embedding=body.embedding,
            name=body.meta.name if body.meta else None,
            tags=body.meta.tags if body.meta else None,
            when_to_use=body.meta.when_to_use if body.meta else None,
            author=body.meta.author if body.meta else None,
            channel=body.channel,
            evolution_meta=evolution_meta,
            parent_version_id=body.parent_version_id,
            change_summary=body.change_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity, version = result
    etag = compute_etag(version.content_json)
    return EntityResponse(
        entity_type=entity.entity_type,
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        version_number=version.version_number,
        channel=body.channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.delete("/{entity_type}/{entity_id}", status_code=204)
async def delete_entity(
    entity_type: str,
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an entity."""
    _validate_type(entity_type)
    svc = EntityService(db)
    deleted = await svc.soft_delete(entity_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entity not found")


#: Sentinel value clients must echo back in the `X-Confirm` header to
#: authorise the destructive ``POST /v1/maintenance/clear-all``. The
#: deliberately-long phrase makes the call un-mistakable in shell
#: history and prevents accidental `curl -X POST ...` from a fat-finger.
CLEAR_ALL_CONFIRM_TOKEN = "yes-i-really-mean-it"


@router.post("/maintenance/clear-all")
async def clear_all_entities(
    entity_type: str | None = None,
    x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete all entities, optionally filtered by type.

    **Destructive — protected by two independent guards:**

    1. ``auth.require_scope("clear:all")`` — the caller must hold the
       ``clear:all`` scope. Anonymous opt-in callers always 403 here
       (empty scope set); a personal-key holder without the scope
       also 403s. Only the deployment admin (or an explicitly-issued
       maintenance key) can reach the handler body.
    2. ``X-Confirm: yes-i-really-mean-it`` header — even when the
       caller has the scope, the phrase must be typed verbatim so a
       fat-fingered `curl` can't wipe CARE's library by accident.

    The scope check runs **first** so unauthorised callers don't even
    learn whether the X-Confirm token matches.

    Args:
        entity_type: Optional entity type to clear (step, chain, agent,
            agent_skill, memory_card). If not provided, clears all
            entity types.

    Returns:
        Dictionary with counts of deleted entities per type.

    Raises:
        HTTPException 403 Forbidden: when the caller lacks ``clear:all``.
        HTTPException 412 Precondition Failed: when ``X-Confirm`` is
            missing or has the wrong value.
        HTTPException 400 Bad Request: when ``entity_type`` is invalid.
    """
    auth.require_scope(SCOPE_CLEAR_ALL)

    if x_confirm != CLEAR_ALL_CONFIRM_TOKEN:
        raise HTTPException(
            status_code=412,
            detail=(
                "Precondition Failed: clear_all is destructive and requires "
                f"`X-Confirm: {CLEAR_ALL_CONFIRM_TOKEN}` header."
            ),
        )

    svc = EntityService(db)

    # Validate entity_type if provided
    if entity_type:
        if entity_type not in VALID_ENTITY_TYPES.values():
            raise HTTPException(
                status_code=400,
                detail=f"Invalid entity type '{entity_type}'. Must be one of: {list(VALID_ENTITY_TYPES.values())}",
            )

    counts = await svc.clear_all(entity_type)
    return {"deleted": counts}
