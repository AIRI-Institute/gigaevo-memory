"""Version management router: list, get, diff, revert, pin, promote."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db
from ..models.requests import PinRequest, PromoteRequest, RevertRequest
from ..models.responses import DiffResponse, EntityResponse, VersionDetail, VersionInfo
from ..services.entity_service import VALID_ENTITY_TYPES, EntityService, compute_etag

router = APIRouter()


def _validate_type(entity_type: str) -> str:
    # Accept both hyphenated (memory-cards) and underscore (memory_cards) formats
    normalized = entity_type.replace("-", "_")
    if normalized not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity type '{entity_type}'.",
        )
    return normalized


@router.get(
    "/{entity_type}/{entity_id}/versions",
    response_model=list[VersionInfo],
)
async def list_versions(
    entity_type: str,
    entity_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all versions of an entity with pagination."""
    _validate_type(entity_type)
    svc = EntityService(db)
    versions = await svc.list_versions(entity_id, limit=limit, offset=offset)
    return [
        VersionInfo(
            version_id=str(v.version_id),
            entity_id=str(v.entity_id),
            version_number=v.version_number,
            author=v.author,
            change_summary=v.change_summary,
            evolution_meta=v.evolution_meta,
            parents=[str(p) for p in v.parents] if v.parents else None,
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.get(
    "/{entity_type}/{entity_id}/versions/{version_id}",
    response_model=VersionDetail,
)
async def get_version(
    entity_type: str,
    entity_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific version with its content."""
    _validate_type(entity_type)
    svc = EntityService(db)
    version = await svc.get_version(version_id)
    if version is None or version.entity_id != entity_id:
        raise HTTPException(status_code=404, detail="Version not found")
    return VersionDetail(
        version_id=str(version.version_id),
        entity_id=str(version.entity_id),
        version_number=version.version_number,
        author=version.author,
        change_summary=version.change_summary,
        evolution_meta=version.evolution_meta,
        parents=[str(p) for p in version.parents] if version.parents else None,
        created_at=version.created_at,
        content=version.content_json,
        meta=version.meta_json,
    )


@router.get(
    "/{entity_type}/{entity_id}/diff",
    response_model=DiffResponse,
)
async def diff_versions(
    entity_type: str,
    entity_id: uuid.UUID,
    from_ver: uuid.UUID = Query(alias="from"),
    to_ver: uuid.UUID = Query(alias="to"),
    db: AsyncSession = Depends(get_db),
):
    """Compute a JSON patch between two versions."""
    _validate_type(entity_type)
    svc = EntityService(db)
    result = await svc.diff_versions(from_ver, to_ver)
    if result is None:
        raise HTTPException(status_code=404, detail="One or both versions not found")
    return DiffResponse(
        from_version=result["from_version"],
        to_version=result["to_version"],
        patch={"ops": result["patch"]},
    )


@router.post(
    "/{entity_type}/{entity_id}/revert",
    response_model=EntityResponse,
)
async def revert(
    entity_type: str,
    entity_id: uuid.UUID,
    body: RevertRequest,
    db: AsyncSession = Depends(get_db),
):
    """Revert: create a new version with content from an old version."""
    _validate_type(entity_type)
    svc = EntityService(db)
    result = await svc.revert(entity_id, uuid.UUID(body.target_version_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Entity or target version not found")

    entity, version = result
    etag = compute_etag(version.content_json)
    return EntityResponse(
        entity_type=entity.entity_type,
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel="latest",
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.post("/{entity_type}/{entity_id}/pin", status_code=200)
async def pin_channel(
    entity_type: str,
    entity_id: uuid.UUID,
    body: PinRequest,
    db: AsyncSession = Depends(get_db),
):
    """Pin a channel to a specific version."""
    _validate_type(entity_type)
    svc = EntityService(db)
    ok = await svc.pin_channel(entity_id, body.channel, body.version_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Entity or version not found")
    return {"status": "pinned", "channel": body.channel, "version_id": body.version_id}


@router.post("/{entity_type}/{entity_id}/promote", status_code=200)
async def promote(
    entity_type: str,
    entity_id: uuid.UUID,
    body: PromoteRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Promote: copy one channel pointer to another (default: latest → stable)."""
    _validate_type(entity_type)
    from_ch = body.from_channel if body else "latest"
    to_ch = body.to_channel if body else "stable"
    svc = EntityService(db)
    ok = await svc.promote(entity_id, from_ch, to_ch)
    if not ok:
        raise HTTPException(status_code=404, detail="Entity not found or source channel empty")
    return {"status": "promoted", "from": from_ch, "to": to_ch}


# =============================================================================
# Typed endpoints for backward compatibility and discoverability
# These endpoints use explicit entity paths instead of generic {entity_type}
# =============================================================================


@router.get("/steps/{step_id}/versions", response_model=list[VersionInfo])
async def list_step_versions(
    step_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all versions of a step with pagination."""
    return await list_versions("steps", step_id, limit, offset, db)


@router.get("/chains/{chain_id}/versions", response_model=list[VersionInfo])
async def list_chain_versions(
    chain_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all versions of a chain with pagination."""
    return await list_versions("chains", chain_id, limit, offset, db)


@router.get("/agents/{agent_id}/versions", response_model=list[VersionInfo])
async def list_agent_versions(
    agent_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all versions of an agent with pagination."""
    return await list_versions("agents", agent_id, limit, offset, db)


@router.get("/memory-cards/{memory_card_id}/versions", response_model=list[VersionInfo])
async def list_memory_card_versions(
    memory_card_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all versions of a memory card with pagination."""
    return await list_versions("memory_cards", memory_card_id, limit, offset, db)


@router.get("/steps/{step_id}/versions/{version_id}", response_model=VersionDetail)
async def get_step_version(
    step_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific step version with its content."""
    return await get_version("steps", step_id, version_id, db)


@router.get("/chains/{chain_id}/versions/{version_id}", response_model=VersionDetail)
async def get_chain_version(
    chain_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific chain version with its content."""
    return await get_version("chains", chain_id, version_id, db)


@router.get("/agents/{agent_id}/versions/{version_id}", response_model=VersionDetail)
async def get_agent_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific agent version with its content."""
    return await get_version("agents", agent_id, version_id, db)


@router.get("/memory-cards/{memory_card_id}/versions/{version_id}", response_model=VersionDetail)
async def get_memory_card_version(
    memory_card_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific memory card version with its content."""
    return await get_version("memory_cards", memory_card_id, version_id, db)
