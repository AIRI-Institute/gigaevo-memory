"""Typed CRUD router for agent_skill entities.

`agent_skill` is the GigaEvo Memory entity type for portable AgentSkills
(SKILL.md folders resolved from `github://`, `local://`, `module://` URIs
plus SHA-pinned manifests). CARE persists every resolved skill here so
generated chains can reference skills by stable entity_id and so MAGE's
capability lookup can search them.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
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
from ..models.responses import AgentSkillPageResponse, AgentSkillResponse
from ..services.entity_service import (
    EntityService,
    compute_etag,
    entity_metadata_kwargs,
)

router = APIRouter(prefix="/v1/agent-skills", tags=["agent_skills"])


def _skill_tool_tokens(version) -> list[str]:
    """Pull the `allowed_tools` token list out of a version's content.

    Returns an empty list when the field is missing or malformed —
    callers that filter on a non-empty requirement will reject the
    skill, callers filtering for "doesn't require X" will accept it.
    """
    content = version.content_json or {}
    tools = content.get("allowed_tools")
    if isinstance(tools, list):
        return [str(t) for t in tools]
    return []


def _filter_skills_by_tools(
    items: list,
    *,
    requires_tool: list[str] | None,
    excludes_tool: list[str] | None,
) -> list:
    """Post-filter ``(entity, version)`` pairs by their allowed_tools.

    Semantics (both AND across the lists):
      * ``requires_tool=["Bash", "Read"]`` → keep skills whose
        ``allowed_tools`` contains BOTH ``Bash`` and ``Read``.
      * ``excludes_tool=["Bash"]`` → drop skills that list ``Bash``.

    Filters are applied **in memory** because the underlying field
    lives inside ``EntityVersion.content_json`` (JSONB); the catalogue
    is small enough that walking 200 rows per request is cheaper than
    the JOIN+JSONB-operator alternative. Pagination is preserved by
    the router fetching a wider window when filters are active.
    """
    if not requires_tool and not excludes_tool:
        return items

    req = set(requires_tool or ())
    exc = set(excludes_tool or ())

    out = []
    for entity, version in items:
        tools = set(_skill_tool_tokens(version))
        if req and not req.issubset(tools):
            continue
        if exc and exc & tools:
            continue
        out.append((entity, version))
    return out


def _agent_skill_response(entity, version, channel: str) -> AgentSkillResponse:
    """Build an AgentSkillResponse from an Entity + EntityVersion pair.

    Centralises etag + library-metadata plumbing so every endpoint
    surfaces the same shape to CARE.
    """
    etag = compute_etag(version.content_json)
    return AgentSkillResponse(
        entity_type="agent_skill",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        version_number=version.version_number,
        channel=channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
        **entity_metadata_kwargs(entity),
    )


@router.post("", status_code=201, response_model=AgentSkillResponse)
async def create_agent_skill(
    body: EntityCreateRequest,
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent_skill entity with its first version.

    Authenticated callers that omit ``meta.namespace`` get their writes
    auto-scoped to ``auth.owner`` via the shared
    :func:`default_namespace_for` helper. Anonymous opt-in callers
    keep the request body's namespace as-is.
    """
    svc = EntityService(db)
    entity_type = "agent_skills"
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

    return _agent_skill_response(entity, version, body.channel)


@router.get("", response_model=AgentSkillPageResponse)
async def list_agent_skills(
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
        description="Sort direction. Default `desc` so the catalogue shows recently-used skills first.",
    ),
    favourites_only: bool = Query(
        False,
        description="When true, only return skills flagged `favourite=TRUE`.",
    ),
    tags: list[str] | None = Query(
        None,
        description="Filter to skills whose `tags` JSONB array contains ALL listed tokens (AND semantics).",
    ),
    q: str | None = Query(
        None,
        description="Case-insensitive substring across display_name / name / description.",
    ),
    namespace: str | None = Query(
        None,
        description=(
            "Restrict to a single CARE namespace. When omitted and "
            "the caller is authenticated, the server auto-scopes to "
            "``auth.owner`` unless the caller holds the ``read:any`` "
            "scope."
        ),
    ),
    requires_tool: list[str] | None = Query(
        None,
        description=(
            "Restrict to skills whose `allowed_tools` array contains "
            "ALL listed tokens (AND semantics). Repeat the param to "
            "stack constraints: `?requires_tool=Read&requires_tool=Write` "
            "→ skills that need both Read and Write."
        ),
    ),
    excludes_tool: list[str] | None = Query(
        None,
        description=(
            "Drop skills that mention ANY of the listed tokens in "
            "their `allowed_tools`. Useful for MAGE-side capability "
            "lookup when the user doesn't want a skill that requires "
            "(e.g.) `Bash`."
        ),
    ),
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """List agent_skills with CARE library sort/filter knobs.

    Authenticated callers without an explicit ``?namespace`` are
    auto-scoped to ``auth.owner`` (mirrors writes-side auto-scoping;
    bypass with the ``read:any`` scope). Anonymous callers in opt-in
    deployments keep the "list everything" semantics.

    Defaults match the CARE catalogue view: recently-used skills first.
    """
    effective_namespace = default_read_namespace_for(namespace, auth)
    svc = EntityService(db)
    # Tool filters operate on `content.allowed_tools` (JSONB) which
    # `list_entities` doesn't push down; we fetch a wider window so
    # the post-filter has enough candidates to honour `limit`.
    has_tool_filter = bool(requires_tool or excludes_tool)
    fetch_limit = min(limit * 4, 200) if has_tool_filter else limit
    items, next_cursor, has_more = await svc.list_entities(
        entity_type="agent_skill",
        limit=fetch_limit,
        offset=offset,
        cursor=cursor,
        channel=channel,
        sort_by=sort_by,
        sort_dir=sort_dir,
        favourites_only=favourites_only,
        tags=tags,
        q=q,
        namespace=effective_namespace,
    )
    if has_tool_filter:
        items = _filter_skills_by_tools(
            items,
            requires_tool=requires_tool,
            excludes_tool=excludes_tool,
        )
        items = items[:limit]
        # The post-filter may have dropped the cursor's last-row,
        # invalidating its position; don't emit a cursor that the
        # next request can't use to continue.
        next_cursor = None
        has_more = False  # client should fall back to offset for tool-filtered pagination
    response.headers["X-Has-More"] = "true" if has_more else "false"
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return AgentSkillPageResponse(
        items=[_agent_skill_response(entity, version, channel) for entity, version in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/{agent_skill_id}", response_model=AgentSkillResponse)
async def get_agent_skill(
    agent_skill_id: uuid.UUID,
    channel: str = "latest",
    if_none_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Get an agent_skill by ID, resolving the channel to a specific version."""
    svc = EntityService(db)
    result = await svc.get_entity(agent_skill_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="AgentSkill not found")

    entity, version = result
    if entity.entity_type != "agent_skill":
        raise HTTPException(status_code=404, detail="Entity is not an agent_skill")

    etag = compute_etag(version.content_json)

    # Conditional GET: return 304 if content unchanged
    if if_none_match and if_none_match == etag:
        return Response(status_code=304)

    return _agent_skill_response(entity, version, channel)


@router.put("/{agent_skill_id}", response_model=AgentSkillResponse)
async def update_agent_skill(
    agent_skill_id: uuid.UUID,
    body: EntityUpdateRequest,
    if_match: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Update an agent_skill by creating a new immutable version."""
    svc = EntityService(db)

    # Optimistic concurrency check
    if if_match:
        current = await svc.get_entity(agent_skill_id, body.channel)
        if current is None:
            raise HTTPException(status_code=404, detail="AgentSkill not found")
        current_etag = compute_etag(current[1].content_json)
        if if_match != current_etag:
            raise HTTPException(
                status_code=412, detail="Precondition Failed: ETag mismatch"
            )

    evolution_meta = body.evolution_meta.model_dump() if body.evolution_meta else None

    try:
        result = await svc.update_entity(
            entity_id=agent_skill_id,
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
        raise HTTPException(status_code=404, detail="AgentSkill not found")

    entity, version = result
    return _agent_skill_response(entity, version, body.channel)


@router.patch("/{agent_skill_id}", response_model=AgentSkillResponse)
async def patch_agent_skill_metadata(
    agent_skill_id: uuid.UUID,
    body: EntityPatchRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Partial update of CARE-mutable entity-level fields.

    Mutates ``display_name`` / ``description`` / ``tags`` / ``favourite``
    on the entity row without creating a new version. CARE uses this
    when the user renames a skill or toggles its favourite/tags from
    the catalogue screen.
    """
    svc = EntityService(db)
    entity = await svc.update_metadata(
        agent_skill_id,
        display_name=body.display_name,
        description=body.description,
        tags=body.tags,
        favourite=body.favourite,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="AgentSkill not found")
    if entity.entity_type != "agent_skill":
        raise HTTPException(status_code=404, detail="Entity is not an agent_skill")

    result = await svc.get_entity(agent_skill_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="AgentSkill has no versions")
    _, version = result
    return _agent_skill_response(entity, version, channel)


@router.post("/{agent_skill_id}/favourite", response_model=AgentSkillResponse)
async def toggle_agent_skill_favourite(
    agent_skill_id: uuid.UUID,
    body: FavouriteRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Set the favourite flag on a skill (idempotent, no new version)."""
    svc = EntityService(db)
    entity = await svc.set_favourite(agent_skill_id, body.favourite)
    if entity is None:
        raise HTTPException(status_code=404, detail="AgentSkill not found")
    if entity.entity_type != "agent_skill":
        raise HTTPException(status_code=404, detail="Entity is not an agent_skill")

    result = await svc.get_entity(agent_skill_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="AgentSkill has no versions")
    _, version = result
    return _agent_skill_response(entity, version, channel)


@router.post("/{agent_skill_id}/run-recorded", response_model=AgentSkillResponse)
async def record_agent_skill_run(
    agent_skill_id: uuid.UUID,
    body: RecordRunRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Bump ``run_count`` and set ``last_run_at = now()``.

    CARE calls this every time a chain successfully exercises this
    skill so the catalogue can sort by usage/recency.
    """
    svc = EntityService(db)
    entity = await svc.record_run(agent_skill_id, run_id=body.run_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="AgentSkill not found")
    if entity.entity_type != "agent_skill":
        raise HTTPException(status_code=404, detail="Entity is not an agent_skill")

    result = await svc.get_entity(agent_skill_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="AgentSkill has no versions")
    _, version = result
    return _agent_skill_response(entity, version, channel)


@router.delete("/{agent_skill_id}", status_code=204)
async def delete_agent_skill(
    agent_skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an agent_skill."""
    svc = EntityService(db)
    deleted = await svc.soft_delete(agent_skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="AgentSkill not found")
