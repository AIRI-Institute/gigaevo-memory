"""Typed CRUD router for chain entities with CARL DAG validation."""

import uuid
from typing import List

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
from ..models.responses import ChainResponse, DifferentialChannelView, LineageResponse
from ..services.entity_service import (
    EntityService,
    compute_etag,
    entity_metadata_kwargs,
)

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


def _chain_response(entity, version, channel: str) -> ChainResponse:
    """Build a ChainResponse from an Entity + EntityVersion pair.

    Centralises etag + library-metadata plumbing so every endpoint
    surfaces the same shape to CARE.
    """
    etag = compute_etag(version.content_json)
    return ChainResponse(
        entity_type="chain",
        entity_id=str(entity.entity_id),
        version_id=str(version.version_id),
        channel=channel,
        etag=etag,
        meta=version.meta_json or {},
        content=version.content_json,
        **entity_metadata_kwargs(entity),
    )


@router.post("", status_code=201, response_model=ChainResponse)
async def create_chain(
    body: EntityCreateRequest,
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chain entity with its first version.

    Authenticated callers (opt-in mode with a valid `X-API-Key`, or
    strict mode) get their `meta.namespace` defaulted to `auth.owner`
    when unset — the standard CARE auto-scoping path. Explicit
    namespaces in the body are respected verbatim.
    """
    # Validate CARL DAG structure
    _validate_carl_dag(body.content)

    svc = EntityService(db)
    entity_type = "chains"

    evolution_meta = body.evolution_meta.model_dump() if body.evolution_meta else None
    namespace = default_namespace_for(body.meta.namespace, auth)

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

    return _chain_response(entity, version, body.channel)


@router.get("", response_model=List[ChainResponse])
async def list_chains(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(
        None,
        description=(
            "Keyset-pagination cursor returned by a previous call's "
            "`X-Next-Cursor` response header. When supplied, ``offset`` "
            "is ignored and the cursor's stable position is used "
            "instead — safe past 10k entities. Only valid with the "
            "default sort (`created_at asc`); the server silently "
            "ignores the cursor on non-default sorts."
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
        description="Sort direction. Default `desc` so the library shows the most recently used chains on top.",
    ),
    favourites_only: bool = Query(
        False,
        description="When true, only return chains flagged `favourite=TRUE`.",
    ),
    tags: list[str] | None = Query(
        None,
        description="Filter to chains whose `tags` JSONB array contains ALL listed tokens (AND semantics).",
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
    """List chains with CARE library sort/filter knobs.

    Defaults match the LibraryScreen's home view: chains in the user's
    namespace, sorted by ``last_run_at DESC`` so recently-run chains
    surface first.

    When the caller is authenticated and doesn't pass an explicit
    ``?namespace`` filter, results are auto-scoped to ``auth.owner``
    (mirroring the writes-side auto-scoping) so a personal-key holder
    only sees their own chains. The ``read:any`` scope opts out of
    that scoping. Anonymous callers in opt-in deployments keep their
    current "list everything" semantics.

    **Pagination**: response carries two headers — ``X-Next-Cursor``
    (opaque cursor string, only present when ``has_more=True``) and
    ``X-Has-More`` (``"true" | "false"``). Pass the cursor back as
    ``?cursor=...`` to fetch the next page. Cursor pagination is
    stable past 10k entities; offset pagination remains supported for
    callers that haven't migrated yet.
    """
    effective_namespace = default_read_namespace_for(namespace, auth)
    svc = EntityService(db)
    items, next_cursor, has_more = await svc.list_entities(
        entity_type="chain",
        limit=limit,
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
    response.headers["X-Has-More"] = "true" if has_more else "false"
    if next_cursor:
        response.headers["X-Next-Cursor"] = next_cursor
    return [_chain_response(entity, version, channel) for entity, version in items]


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

    return _chain_response(entity, version, channel)


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
    return _chain_response(entity, version, body.channel)


@router.patch("/{chain_id}", response_model=ChainResponse)
async def patch_chain_metadata(
    chain_id: uuid.UUID,
    body: EntityPatchRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Partial update of CARE-mutable entity-level fields.

    Mutates ``display_name`` / ``description`` / ``tags`` / ``favourite``
    on the entity row without creating a new chain version. CARE uses
    this when the user renames a chain or toggles its favourite/tags
    from the library screen.
    """
    svc = EntityService(db)
    entity = await svc.update_metadata(
        chain_id,
        display_name=body.display_name,
        description=body.description,
        tags=body.tags,
        favourite=body.favourite,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Chain not found")
    if entity.entity_type != "chain":
        raise HTTPException(status_code=404, detail="Entity is not a chain")

    result = await svc.get_entity(chain_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Chain has no versions")
    _, version = result
    return _chain_response(entity, version, channel)


@router.post("/{chain_id}/favourite", response_model=ChainResponse)
async def toggle_chain_favourite(
    chain_id: uuid.UUID,
    body: FavouriteRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Set the favourite flag on a chain (idempotent, no new version)."""
    svc = EntityService(db)
    entity = await svc.set_favourite(chain_id, body.favourite)
    if entity is None:
        raise HTTPException(status_code=404, detail="Chain not found")
    if entity.entity_type != "chain":
        raise HTTPException(status_code=404, detail="Entity is not a chain")

    result = await svc.get_entity(chain_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Chain has no versions")
    _, version = result
    return _chain_response(entity, version, channel)


@router.post("/{chain_id}/run-recorded", response_model=ChainResponse)
async def record_chain_run(
    chain_id: uuid.UUID,
    body: RecordRunRequest,
    channel: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    """Bump ``run_count`` and set ``last_run_at = now()``.

    CARE calls this every time a saved chain is executed so the library
    can sort by usage/recency.
    """
    svc = EntityService(db)
    entity = await svc.record_run(chain_id, run_id=body.run_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Chain not found")
    if entity.entity_type != "chain":
        raise HTTPException(status_code=404, detail="Entity is not a chain")

    result = await svc.get_entity(chain_id, channel)
    if result is None:
        raise HTTPException(status_code=404, detail="Chain has no versions")
    _, version = result
    return _chain_response(entity, version, channel)


@router.get("/{chain_id}/lineage", response_model=LineageResponse)
async def get_chain_lineage(
    chain_id: uuid.UUID,
    channel: str = "latest",
    version_id: uuid.UUID | None = None,
    max_depth: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Return the ancestry DAG for a chain (or a specific version).

    Walks `entity_versions.parents` recursively starting from the
    version pinned to ``channel`` (or ``version_id`` when supplied),
    de-duped by ``version_id``. CARE's library uses this for the
    evolution-tree visualisation triggered from the "Show lineage"
    row action.
    """
    svc = EntityService(db)
    data = await svc.get_lineage(
        chain_id,
        channel=channel,
        version_id=version_id,
        max_depth=max_depth,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Chain or version not found")
    # Validate the entity is actually a chain (so the lineage endpoint
    # mounted under /v1/chains doesn't accidentally serve other types).
    entity_result = await svc.get_entity(chain_id, channel)
    if entity_result is None or entity_result[0].entity_type != "chain":
        raise HTTPException(status_code=404, detail="Entity is not a chain")
    return LineageResponse.model_validate(data)


@router.get(
    "/{chain_id}/versions/beating",
    response_model=DifferentialChannelView,
)
async def list_versions_beating_channel(
    chain_id: uuid.UUID,
    channel: str = Query(
        "stable",
        description="Baseline channel to compare against (typically `stable`).",
    ),
    objective: str = Query(
        "fitness_score",
        description=(
            "Which evolution_meta value to compare. `fitness_score` "
            "reads the standardised top-level field (legacy `fitness` "
            "fallback); any other string is looked up in "
            "`evolution_meta.objectives` (e.g. `accuracy`, `latency_ms`)."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    sort_dir: str = Query(
        "desc",
        pattern="^(asc|desc)$",
        description="Sort direction for the winners list by `value`.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return chain versions that beat the baseline channel on an objective.

    CARE's "promotion candidates" view — pinpoints versions that
    outperformed the currently-blessed `stable` pin on a chosen metric,
    so a human can manually promote a winner.

    Returns ``404`` if the chain entity is missing or soft-deleted.
    Returns a structured ``baseline_value=null`` + ``winners=[]``
    payload when the baseline channel isn't pinned or doesn't carry the
    requested objective — so the UI can render a meaningful empty
    state without inferring the cause from a 404.
    """
    svc = EntityService(db)
    data = await svc.find_versions_beating(
        chain_id,
        baseline_channel=channel,
        objective=objective,
        limit=limit,
        sort_dir=sort_dir,
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Chain not found")

    # Restrict to chains so the endpoint mounted under /v1/chains
    # doesn't accidentally surface other entity types if the same
    # entity_id happens to exist in another type's tree.
    entity_result = await svc.get_entity(chain_id, channel)
    # ``get_entity`` may return the chain via the `latest` fallback
    # even when the requested baseline isn't pinned. We only need to
    # know it's a chain entity.
    if entity_result is None or entity_result[0].entity_type != "chain":
        raise HTTPException(status_code=404, detail="Entity is not a chain")
    return DifferentialChannelView.model_validate(data)


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
