"""Bulk save endpoint — `POST /v1/bulk/save`.

Designed for CARE's `care import ./generated_chains/*.json` flow:
a mixed list of entities submitted in one request, persisted serially
with per-item error isolation.

Authenticates via `Depends(require_api_key)` (dual-mode — anonymous
in opt-in deployments, strict 401 in production). When an
authenticated caller omits `item.meta.namespace`, the server defaults
it to `auth.owner` so writes auto-scope to the issuing principal.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthContext, default_namespace_for, require_api_key
from ..db.session import get_db
from ..models.requests import BulkSaveItem, BulkSaveRequest
from ..models.responses import BulkSaveItemResult, BulkSaveResponse
from ..services.entity_service import VALID_ENTITY_TYPES, EntityService

router = APIRouter()


#: Reverse lookup: singular entity_type → plural form the service expects.
_SINGULAR_TO_PLURAL = {v: k for k, v in VALID_ENTITY_TYPES.items()}


async def _save_one(
    svc: EntityService,
    item: BulkSaveItem,
) -> tuple[bool, dict[str, str] | None, str | None]:
    """Persist a single bulk item; return (success, entity_ref, error)."""
    plural = _SINGULAR_TO_PLURAL.get(item.entity_type)
    if plural is None:
        return (
            False,
            None,
            f"Invalid entity_type '{item.entity_type}'. "
            f"Must be one of: {sorted(_SINGULAR_TO_PLURAL)}",
        )

    evolution_meta = (
        item.evolution_meta.model_dump() if item.evolution_meta else None
    )

    try:
        if item.entity_id is None:
            entity, version = await svc.create_entity(
                entity_type_plural=plural,
                name=item.meta.name,
                content=item.content,
                embedding=item.embedding,
                tags=item.meta.tags,
                when_to_use=item.meta.when_to_use,
                author=item.meta.author,
                namespace=item.meta.namespace,
                channel=item.channel,
                evolution_meta=evolution_meta,
                parent_version_id=item.parent_version_id,
            )
        else:
            result = await svc.update_entity(
                entity_id=uuid.UUID(item.entity_id),
                content=item.content,
                embedding=item.embedding,
                name=item.meta.name,
                tags=item.meta.tags,
                when_to_use=item.meta.when_to_use,
                author=item.meta.author,
                channel=item.channel,
                evolution_meta=evolution_meta,
                parent_version_id=item.parent_version_id,
                change_summary=item.change_summary,
            )
            if result is None:
                return (False, None, f"Entity {item.entity_id} not found")
            entity, version = result
    except ValueError as exc:
        return (False, None, str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return (False, None, f"{type(exc).__name__}: {exc}")

    return (
        True,
        {
            "entity_type": entity.entity_type,
            "entity_id": str(entity.entity_id),
            "version_id": str(version.version_id),
            "channel": item.channel,
        },
        None,
    )


def _apply_namespace_default(
    item: BulkSaveItem, auth: AuthContext
) -> BulkSaveItem:
    """Default ``item.meta.namespace`` for authenticated callers via
    the shared :func:`default_namespace_for` helper.

    Returns a new ``BulkSaveItem`` (never mutates the request body).
    Short-circuits to the original item when the helper agrees with
    the existing value (anonymous caller, explicit namespace, etc.).
    """
    resolved = default_namespace_for(item.meta.namespace, auth)
    if resolved == item.meta.namespace:
        return item
    new_meta = item.meta.model_copy(update={"namespace": resolved})
    return item.model_copy(update={"meta": new_meta})


@router.post("/bulk/save", response_model=BulkSaveResponse)
async def bulk_save(
    body: BulkSaveRequest,
    auth: AuthContext = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
) -> BulkSaveResponse:
    """Persist a mixed list of entities in a single request.

    Used by CARE's `care import` (and any future migration / batch-load
    tooling). Items are processed in submission order with per-item
    error isolation by default — a failure at index 3 doesn't roll back
    index 0–2. Pass `stop_on_error=True` to abort on the first failure.

    When the caller is authenticated (i.e. an `X-API-Key` header was
    supplied and validated) and an item omits `meta.namespace`, the
    server defaults the item's namespace to `auth.owner`. This is the
    auto-namespacing path that makes CARE's `care import` work out of
    the box without each chain needing an explicit namespace.

    Returns a per-item results array so the client can correlate
    successes with their input positions.
    """
    svc = EntityService(db)
    results: list[BulkSaveItemResult] = []
    successes = 0
    errors = 0

    for idx, item in enumerate(body.items):
        scoped_item = _apply_namespace_default(item, auth)
        ok, ref, err = await _save_one(svc, scoped_item)
        results.append(
            BulkSaveItemResult(
                index=idx, success=ok, entity_ref=ref, error=err
            )
        )
        if ok:
            successes += 1
        else:
            errors += 1
            if body.stop_on_error:
                break

    return BulkSaveResponse(
        results=results, success_count=successes, error_count=errors
    )
