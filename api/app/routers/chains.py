"""Typed CRUD router for chain entities with CARL DAG validation."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db
from ..models.requests import EntityCreateRequest, EntityUpdateRequest
from ..models.responses import ChainResponse
from ..services.entity_service import EntityService, compute_etag

router = APIRouter(prefix="/v1/chains", tags=["chains"])


def _validate_carl_dag(content: dict) -> None:
    """Validate CARL chain structure and DAG properties.

    Ensures:
    - Required fields exist (version, max_workers, metadata, search_config, steps)
    - Steps array is non-empty
    - Each step has a unique number
    - All step dependencies reference existing step numbers
    - The graph is acyclic (no circular dependencies)
    """
    # Check required top-level fields
    required_fields = ["version", "max_workers", "metadata", "search_config", "steps"]
    for field in required_fields:
        if field not in content:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid CARL chain: missing required field '{field}'",
            )

    steps = content.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid CARL chain: steps must be a non-empty array",
        )

    # Validate step uniqueness and collect dependencies
    step_numbers = set()
    step_dependencies = {}  # step_number -> list of dependencies

    for step in steps:
        step_number = step.get("number")
        if step_number is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid CARL chain: step missing 'number' field",
            )

        if step_number in step_numbers:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid CARL chain: duplicate step number {step_number}",
            )
        step_numbers.add(step_number)

        # Collect dependencies
        dependencies = step.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid CARL chain: dependencies must be an array for step {step_number}",
            )
        step_dependencies[step_number] = dependencies

        # Verify dependencies reference existing steps
        for dep in dependencies:
            if dep not in step_numbers:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid CARL chain: step {step_number} has dependency on non-existent step {dep}",
                )

    # Check for cycles using DFS
    visited = set()
    rec_stack = set()

    def has_cycle(step_number: int) -> bool:
        visited.add(step_number)
        rec_stack.add(step_number)

        for neighbor in step_dependencies.get(step_number, []):
            if neighbor not in visited:
                if has_cycle(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(step_number)
        return False

    for step_number in step_numbers:
        if step_number not in visited:
            if has_cycle(step_number):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid CARL chain: circular dependencies detected",
                )


@router.post("", status_code=201, response_model=ChainResponse)
async def create_chain(
    body: EntityCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new chain entity with its first version."""
    # Validate CARL DAG structure
    _validate_carl_dag(body.content)

    svc = EntityService(db)
    entity_type = "chains"

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
    return ChainResponse(
        entity_type="chain",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel=body.channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.get("", response_model=List[ChainResponse])
async def list_chains(
    limit: int = 50,
    offset: int = 0,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """List all chains with pagination."""
    svc = EntityService(db)
    items, _, _ = await svc.list_entities(
        entity_type="chain",
        limit=limit,
        offset=offset,
        channel=channel,
    )
    return [
        ChainResponse(
            entity_type="chain",
            entity_id=str(entity.entity_id),
            version_id=str(version.version_id),
            channel=channel,
            etag=compute_etag(version.content_json),
            meta=version.meta_json or {},
            content=version.content_json,
        )
        for entity, version in items
    ]


@router.get("/{chain_id}", response_model=ChainResponse)
async def get_chain(
    chain_id: uuid.UUID,
    channel: str = "latest",
    if_none_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Get a chain by ID, resolving the channel to a specific version."""
    svc = EntityService(db)
    result = await svc.get_entity(chain_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Chain not found")

    entity, version = result
    if entity.entity_type != "chain":
        raise HTTPException(status_code=404, detail="Entity is not a chain")

    etag = compute_etag(version.content_json)

    # Conditional GET: return 304 if content unchanged
    if if_none_match and if_none_match == etag:
        return Response(status_code=304)

    return ChainResponse(
        entity_type="chain",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel=channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.put("/{chain_id}", response_model=ChainResponse)
async def update_chain(
    chain_id: uuid.UUID,
    body: EntityUpdateRequest,
    if_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Update a chain by creating a new immutable version."""
    # Validate CARL DAG structure
    _validate_carl_dag(body.content)

    svc = EntityService(db)

    # Optimistic concurrency check
    if if_match:
        current = await svc.get_entity(chain_id, body.channel)
        if current is None:
            raise HTTPException(status_code=404, detail="Chain not found")
        current_etag = compute_etag(current[1].content_json)
        if if_match != current_etag:
            raise HTTPException(
                status_code=412, detail="Precondition Failed: ETag mismatch"
            )

    evolution_meta = body.evolution_meta.model_dump() if body.evolution_meta else None

    try:
        result = await svc.update_entity(
            entity_id=chain_id,
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
        raise HTTPException(status_code=404, detail="Chain not found")

    entity, version = result
    etag = compute_etag(version.content_json)
    return ChainResponse(
        entity_type="chain",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel=body.channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.delete("/{chain_id}", status_code=204)
async def delete_chain(
    chain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a chain."""
    svc = EntityService(db)
    deleted = await svc.soft_delete(chain_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chain not found")
