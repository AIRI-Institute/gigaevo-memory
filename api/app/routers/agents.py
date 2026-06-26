"""Typed CRUD router for agent entities."""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    AuthContext,
    default_namespace_for,
    default_read_namespace_for,
    require_api_key,
)
from ..db.session import get_db
from ..models.requests import (
    EntityCreateRequest,
    EntityPatchRequest,
    EntityUpdateRequest,
    FavouriteRequest,
    RecordRunRequest,
)
from ..models.responses import AgentPageResponse, AgentResponse
from ..services.entity_service import EntityService, compute_etag, entity_metadata_kwargs

router = APIRouter(prefix="/v1/agents", tags=["agents"])


def _agent_response(entity, version, channel: str) -> AgentResponse:
    """Build an AgentResponse from an Entity + EntityVersion pair.

    Centralises the (otherwise repeated) ``etag`` + library-metadata
    plumbing so every endpoint surfaces the same shape to CARE.
    """
    etag = compute_etag(version.content_json)
    return AgentResponse(
        entity_type="agent",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        version_number=version.version_number,
        channel=channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
        **entity_metadata_kwargs(entity),
    )


@router.post("", status_code=201, response_model=AgentResponse)
async def create_agent(
    body: EntityCreateRequest,
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent entity with its first version.

    Authenticated callers that omit ``meta.namespace`` get their writes
    auto-scoped to ``auth.owner`` via the shared
    :func:`default_namespace_for` helper. Anonymous opt-in callers
    keep the request body's namespace as-is (typically ``None``).
    """
    svc = EntityService(db)
    entity_type = "agents"
    namespace = default_namespace_for(body.meta.namespace, auth)

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
            namespace=namespace,
            channel=body.channel,
            evolution_meta=evolution_meta,
            parent_version_id=body.parent_version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _agent_response(entity, version, body.channel)


@router.get("", response_model=AgentPageResponse)
async def list_agents(
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(
        None,
        description=(
            "Keyset-pagination cursor returned by a previous call's "
            "`X-Next-Cursor` response header. Stable past 10k "
            "entities; only valid with the default sort."
        ),
    ),
    channel: str = "latest",
    sort_by: str = Query(
        "last_run_at",
        pattern="^(created_at|last_run_at|run_count|display_name)$",
        description="Field to sort by. Default matches CARE library shape.",
    ),
    sort_dir: str = Query(
        "desc",
        pattern="^(asc|desc)$",
        description="Sort direction. Default `desc` so the library shows the most recently used agents on top.",
    ),
    favourites_only: bool = Query(
        False,
        description="When true, only return agents flagged `favourite=TRUE`.",
    ),
    tags: list[str] | None = Query(
        None,
        description="Filter to agents whose `tags` JSONB array contains ALL listed tokens (AND semantics).",
    ),
    q: str | None = Query(
        None,
        description="Case-insensitive substring match across display_name / name / description.",
    ),
    namespace: str | None = Query(
        None,
        description="Restrict to a single CARE namespace.",
    ),
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """List agents with CARE library sort/filter knobs.

    Authenticated callers without an explicit ``?namespace`` query
    are auto-scoped to ``auth.owner`` (mirrors the writes-side
    auto-scoping). The ``read:any`` scope opts out of that scoping.
    Anonymous callers in opt-in deployments keep the "list
    everything" semantics.

    Defaults match the LibraryScreen's home view: agents in the user's
    namespace, sorted by ``last_run_at DESC`` so recently-used agents
    surface first.
    """
    effective_namespace = default_read_namespace_for(namespace, auth)
    svc = EntityService(db)
    use_iteration_sort = "sort_by" not in request.query_params and "sort_dir" not in request.query_params
    service_sort_by = "created_at" if use_iteration_sort else sort_by
    service_sort_dir = "asc" if use_iteration_sort else sort_dir
    try:
        items, next_cursor, has_more = await svc.list_entities(
            entity_type="agent",
            limit=limit,
            offset=offset,
            cursor=cursor,
            channel=channel,
            sort_by=service_sort_by,
            sort_dir=service_sort_dir,
            favourites_only=favourites_only,
            tags=tags,
            q=q,
            namespace=effective_namespace,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.headers["X-Has-More"] = "true" if has_more else "false"
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return AgentPageResponse(
        items=[_agent_response(entity, version, channel) for entity, version in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


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

    return _agent_response(entity, version, channel)


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
            raise HTTPException(status_code=412, detail="Precondition Failed: ETag mismatch")

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
    return _agent_response(entity, version, body.channel)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def patch_agent_metadata(
    agent_id: uuid.UUID,
    body: EntityPatchRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Partial update of CARE-mutable entity-level fields.

    Mutates ``display_name`` / ``description`` / ``tags`` / ``favourite``
    on the entity row without creating a new version. CARE uses this
    when the user renames an agent or toggles its favourite/tags from
    the library screen.
    """
    svc = EntityService(db)
    entity = await svc.update_metadata(
        agent_id,
        display_name=body.display_name,
        description=body.description,
        tags=body.tags,
        favourite=body.favourite,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if entity.entity_type != "agent":
        raise HTTPException(status_code=404, detail="Entity is not an agent")

    # Resolve the channel-pointed version to return the same shape as GET.
    result = await svc.get_entity(agent_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent has no versions")
    _, version = result
    return _agent_response(entity, version, channel)


@router.post("/{agent_id}/favourite", response_model=AgentResponse)
async def toggle_agent_favourite(
    agent_id: uuid.UUID,
    body: FavouriteRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Set the favourite flag on an agent (idempotent, no new version)."""
    svc = EntityService(db)
    entity = await svc.set_favourite(agent_id, body.favourite)
    if entity is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if entity.entity_type != "agent":
        raise HTTPException(status_code=404, detail="Entity is not an agent")

    result = await svc.get_entity(agent_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent has no versions")
    _, version = result
    return _agent_response(entity, version, channel)


@router.post("/{agent_id}/run-recorded", response_model=AgentResponse)
async def record_agent_run(
    agent_id: uuid.UUID,
    body: RecordRunRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Bump ``run_count`` and set ``last_run_at = now()``.

    Called by CARE (or any client) every time a saved agent is run, so
    the library can sort by usage/recency.
    """
    svc = EntityService(db)
    entity = await svc.record_run(agent_id, run_id=body.run_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if entity.entity_type != "agent":
        raise HTTPException(status_code=404, detail="Entity is not an agent")

    result = await svc.get_entity(agent_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent has no versions")
    _, version = result
    return _agent_response(entity, version, channel)


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
