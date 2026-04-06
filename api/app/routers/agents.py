"""Typed CRUD router for agent entities."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.session import get_db
from ..models.requests import EntityCreateRequest, EntityUpdateRequest
from ..models.responses import AgentResponse
from ..services.entity_service import EntityService, compute_etag

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.post("", status_code=201, response_model=AgentResponse)
async def create_agent(
    body: EntityCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent entity with its first version."""
    svc = EntityService(db)
    entity_type = "agents"

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
    return AgentResponse(
        entity_type="agent",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel=body.channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.get("", response_model=List[AgentResponse])
async def list_agents(
    limit: int = 50,
    offset: int = 0,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """List all agents with pagination."""
    svc = EntityService(db)
    items, _, _ = await svc.list_entities(
        entity_type="agent",
        limit=limit,
        offset=offset,
        channel=channel,
    )
    return [
        AgentResponse(
            entity_type="agent",
            entity_id=str(entity.entity_id),
            version_id=str(version.version_id),
            channel=channel,
            etag=compute_etag(version.content_json),
            meta=version.meta_json or {},
            content=version.content_json,
        )
        for entity, version in items
    ]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID,
    channel: str = "latest",
    if_none_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Get an agent by ID, resolving the channel to a specific version."""
    svc = EntityService(db)
    result = await svc.get_entity(agent_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    entity, version = result
    if entity.entity_type != "agent":
        raise HTTPException(status_code=404, detail="Entity is not an agent")

    etag = compute_etag(version.content_json)

    # Conditional GET: return 304 if content unchanged
    if if_none_match and if_none_match == etag:
        return Response(status_code=304)

    return AgentResponse(
        entity_type="agent",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel=channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    body: EntityUpdateRequest,
    if_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Update an agent by creating a new immutable version."""
    svc = EntityService(db)

    # Optimistic concurrency check
    if if_match:
        current = await svc.get_entity(agent_id, body.channel)
        if current is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        current_etag = compute_etag(current[1].content_json)
        if if_match != current_etag:
            raise HTTPException(
                status_code=412, detail="Precondition Failed: ETag mismatch"
            )

    evolution_meta = body.evolution_meta.model_dump() if body.evolution_meta else None

    try:
        result = await svc.update_entity(
            entity_id=agent_id,
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
        raise HTTPException(status_code=404, detail="Agent not found")

    entity, version = result
    etag = compute_etag(version.content_json)
    return AgentResponse(
        entity_type="agent",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel=body.channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
    )


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an agent."""
    svc = EntityService(db)
    deleted = await svc.soft_delete(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
