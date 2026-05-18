"""Business logic for entity and version CRUD operations."""

import base64
import binascii
import hashlib
import json
import uuid
from datetime import datetime, timezone

import jsonpatch
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.models import Entity, EntityVersion
from ..events.publisher import publish_entity_event
from .search_document_service import (
    delete_entity_search_documents,
    sync_entity_search_documents,
)
from .vector_utils import serialize_vector, validate_vector


def compute_etag(content_json: dict) -> str:
    """Compute SHA-256 ETag from canonical JSON."""
    canonical = json.dumps(content_json, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


VALID_ENTITY_TYPES = {
    "steps": "step",
    "chains": "chain",
    "agents": "agent",
    "agent_skills": "agent_skill",
    "memory_cards": "memory_card",
}

_CURSOR_VERSION = 1


def _encode_cursor(
    created_at: datetime,
    entity_id: uuid.UUID,
    entity_type: str,
    channel: str,
) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "created_at": created_at.isoformat(),
        "entity_id": str(entity_id),
        "entity_type": entity_type,
        "channel": channel,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    entity_type: str,
    channel: str,
) -> tuple[datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(f"{cursor}{padding}")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid cursor payload")
        if payload.get("v") != _CURSOR_VERSION:
            raise ValueError("Unsupported cursor version")
        if payload.get("entity_type") != entity_type:
            raise ValueError("Cursor entity type mismatch")
        if payload.get("channel") != channel:
            raise ValueError("Cursor channel mismatch")

        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError("Cursor timestamp must be timezone-aware")
        entity_id = uuid.UUID(payload["entity_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, binascii.Error) as exc:
        if isinstance(exc, ValueError) and str(exc) in {
            "Unsupported cursor version",
            "Cursor entity type mismatch",
            "Cursor channel mismatch",
            "Cursor timestamp must be timezone-aware",
        }:
            raise
        raise ValueError("Invalid cursor") from exc

    return created_at, entity_id


class EntityService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_metadata_source_version(
        self,
        entity: Entity,
        channel: str,
        metadata_source_version_id: uuid.UUID | None = None,
    ) -> EntityVersion | None:
        if metadata_source_version_id is not None:
            source_version_id = metadata_source_version_id
        else:
            source_version_id_str = entity.channels.get(channel) or entity.channels.get(
                "latest"
            )
            if source_version_id_str is None:
                return None
            try:
                source_version_id = uuid.UUID(source_version_id_str)
            except ValueError:
                return None

        source_version = await self.get_version(source_version_id)
        if source_version is None or source_version.entity_id != entity.entity_id:
            return None
        return source_version

    @staticmethod
    def _resolve_version_metadata(
        entity: Entity,
        source_version: EntityVersion | None,
        *,
        name: str | None,
        tags: list[str] | None,
        when_to_use: str | None,
        author: str | None,
    ) -> dict:
        source_meta = source_version.meta_json or {}
        return {
            "name": name if name is not None else source_meta.get("name", entity.name),
            "tags": tags if tags is not None else source_meta.get("tags", entity.tags),
            "when_to_use": (
                when_to_use
                if when_to_use is not None
                else source_meta.get("when_to_use", entity.when_to_use)
            ),
            "author": author,
            "namespace": source_meta.get("namespace", entity.namespace),
        }

    async def _set_version_embedding(
        self,
        version_id: uuid.UUID,
        embedding: list[float],
    ) -> None:
        validated_embedding = validate_vector(
            embedding,
            expected_dimension=settings.vector_dimension,
            label="embedding",
        )
        await self.db.execute(
            text(
                """
                UPDATE entity_versions
                SET embedding = CAST(:embedding AS vector)
                WHERE version_id = :version_id
                """
            ),
            {
                "version_id": version_id,
                "embedding": serialize_vector(validated_embedding),
            },
        )

    async def _copy_version_embedding(
        self,
        source_version_id: uuid.UUID,
        target_version_id: uuid.UUID,
    ) -> None:
        await self.db.execute(
            text(
                """
                UPDATE entity_versions AS target
                SET embedding = source.embedding
                FROM entity_versions AS source
                WHERE target.version_id = :target_version_id
                  AND source.version_id = :source_version_id
                  AND source.embedding IS NOT NULL
                """
            ),
            {
                "source_version_id": source_version_id,
                "target_version_id": target_version_id,
            },
        )

    def _extract_fitness(self, evolution_meta: dict | None) -> float | None:
        """Pull the canonical fitness scalar out of evolution_meta.

        Prefers the §5 P1 standardised ``fitness_score`` field; falls
        back to the legacy gigaevo-core ``fitness`` alias so pre-2026-05
        rows continue to drive evolved-channel promotion.
        """
        if not evolution_meta:
            return None
        score = evolution_meta.get("fitness_score")
        if score is None:
            score = evolution_meta.get("fitness")
        try:
            return float(score) if score is not None else None
        except (TypeError, ValueError):
            return None

    async def _maybe_promote_evolved_channel(
        self,
        channels: dict[str, str],
        new_version_id: uuid.UUID,
        evolution_meta: dict | None,
    ) -> dict[str, str]:
        """Pin the ``evolved`` channel to ``new_version_id`` when its
        fitness beats whatever's currently pinned there.

        Auto-pin rules (P2 §5 channel `evolved` semantics):
          * No fitness on the new version → no-op.
          * No ``evolved`` channel yet → pin it (first-evolution).
          * Current pin's fitness is missing / unparsable → pin new.
          * New fitness > current → pin new.
          * Otherwise → leave the pin alone (strict ``>``: ties keep the
            incumbent so a re-run with identical score doesn't churn).

        Returns a (possibly new) channels dict; callers should always
        re-assign because dict identity may change.
        """
        new_score = self._extract_fitness(evolution_meta)
        if new_score is None:
            return channels

        current_evolved_id = channels.get("evolved")
        if current_evolved_id is None:
            channels = dict(channels)
            channels["evolved"] = str(new_version_id)
            return channels

        try:
            current_evolved_uuid = uuid.UUID(current_evolved_id)
        except (ValueError, TypeError):
            # Corrupt pointer — overwrite with the known-good new id.
            channels = dict(channels)
            channels["evolved"] = str(new_version_id)
            return channels

        current_version = await self.get_version(current_evolved_uuid)
        current_score = (
            self._extract_fitness(current_version.evolution_meta)
            if current_version is not None
            else None
        )
        if current_score is None or new_score > current_score:
            channels = dict(channels)
            channels["evolved"] = str(new_version_id)
        return channels

    async def create_entity(
        self,
        entity_type_plural: str,
        name: str,
        content: dict,
        embedding: list[float] | None = None,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        namespace: str | None = None,
        channel: str = "latest",
        evolution_meta: dict | None = None,
        parent_version_id: str | None = None,
    ) -> tuple[Entity, EntityVersion]:
        """Create a new entity with its first version."""
        entity_type = VALID_ENTITY_TYPES[entity_type_plural]

        entity_id = uuid.uuid4()
        version_id = uuid.uuid4()

        initial_channels: dict[str, str] = {
            channel: str(version_id),
            "latest": str(version_id),
        }
        # First-time evolution: if the create call carries a
        # fitness_score, automatically pin `evolved` to this version.
        initial_channels = await self._maybe_promote_evolved_channel(
            initial_channels, version_id, evolution_meta
        )

        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            namespace=namespace,
            name=name,
            tags=tags or [],
            when_to_use=when_to_use,
            channels=initial_channels,
            # CARE library metadata defaults. `display_name` mirrors
            # `name` so the library renders something useful on day-one
            # (CARE will let the user override via PATCH later);
            # `description` reuses `when_to_use` for the same reason.
            # `favourite` / `run_count` / `last_run_at` keep their DB
            # defaults (False / 0 / NULL).
            display_name=name[:200],
            description=when_to_use,
        )
        self.db.add(entity)

        parents = [uuid.UUID(parent_version_id)] if parent_version_id else None
        meta_json = {
            "name": name,
            "tags": tags or [],
            "when_to_use": when_to_use,
            "author": author,
            "namespace": namespace,
        }

        version = EntityVersion(
            version_id=version_id,
            entity_id=entity_id,
            version_number=0,  # First version is v0
            content_json=content,
            meta_json=meta_json,
            parents=parents,
            evolution_meta=evolution_meta,
            author=author,
        )
        self.db.add(version)

        await self.db.flush()
        if embedding is not None:
            await self._set_version_embedding(version_id, embedding)
        await sync_entity_search_documents(self.db, entity, version)

        await self.db.commit()
        await self.db.refresh(entity)
        await self.db.refresh(version)

        await publish_entity_event(
            "created",
            str(entity_id),
            entity_type,
            str(version_id),
            channel,
            namespace=entity.namespace,
            tags=list(entity.tags or []),
        )
        return entity, version

    async def get_entity(
        self, entity_id: uuid.UUID, channel: str = "latest"
    ) -> tuple[Entity, EntityVersion] | None:
        """Get entity with resolved channel version."""
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return None

        version_id_str = entity.channels.get(channel)
        if version_id_str is None:
            # Fall back to latest channel, then any available version
            version_id_str = entity.channels.get("latest")
            if version_id_str is None:
                # Get the most recent version
                stmt = (
                    select(EntityVersion)
                    .where(EntityVersion.entity_id == entity_id)
                    .order_by(EntityVersion.created_at.desc())
                    .limit(1)
                )
                result = await self.db.execute(stmt)
                version = result.scalar_one_or_none()
                if version is None:
                    return None
                return entity, version

        version_id = uuid.UUID(version_id_str)
        stmt = select(EntityVersion).where(EntityVersion.version_id == version_id)
        result = await self.db.execute(stmt)
        version = result.scalar_one_or_none()
        if version is None:
            return None

        return entity, version

    async def update_entity(
        self,
        entity_id: uuid.UUID,
        content: dict,
        embedding: list[float] | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
        when_to_use: str | None = None,
        author: str | None = None,
        channel: str = "latest",
        evolution_meta: dict | None = None,
        parent_version_id: str | None = None,
        change_summary: str | None = None,
        copy_embedding_from_version_id: uuid.UUID | None = None,
        metadata_source_version_id: uuid.UUID | None = None,
    ) -> tuple[Entity, EntityVersion] | None:
        """Create a new version for an existing entity."""
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return None

        source_version = await self._get_metadata_source_version(
            entity,
            channel=channel,
            metadata_source_version_id=metadata_source_version_id,
        )

        # Update entity metadata if provided
        if name is not None:
            entity.name = name
        if tags is not None:
            entity.tags = tags
        if when_to_use is not None:
            entity.when_to_use = when_to_use

        # Calculate next version number
        count_stmt = select(func.count(EntityVersion.version_id)).where(
            EntityVersion.entity_id == entity_id
        )
        count_result = await self.db.execute(count_stmt)
        next_version_number = count_result.scalar() or 0

        # Create new version
        version_id = uuid.uuid4()
        parents = None
        if parent_version_id:
            parents = [uuid.UUID(parent_version_id)]
        elif entity.channels.get(channel):
            parents = [uuid.UUID(entity.channels[channel])]

        meta_json = self._resolve_version_metadata(
            entity,
            source_version,
            name=name,
            tags=tags,
            when_to_use=when_to_use,
            author=author,
        )

        version = EntityVersion(
            version_id=version_id,
            entity_id=entity_id,
            version_number=next_version_number,
            content_json=content,
            meta_json=meta_json,
            parents=parents,
            change_summary=change_summary,
            evolution_meta=evolution_meta,
            author=author,
        )
        self.db.add(version)

        # Update channel pointers - always set latest and the specified channel
        channels = dict(entity.channels)
        channels[channel] = str(version_id)
        channels["latest"] = str(version_id)  # Always update latest
        # Auto-promote `evolved` when this version's fitness beats the
        # current pin (or no pin exists yet) — P2 §5.
        channels = await self._maybe_promote_evolved_channel(
            channels, version_id, evolution_meta
        )
        entity.channels = channels

        await self.db.flush()
        if embedding is not None:
            await self._set_version_embedding(version_id, embedding)
        elif copy_embedding_from_version_id is not None:
            await self._copy_version_embedding(
                copy_embedding_from_version_id,
                version_id,
            )
        await sync_entity_search_documents(self.db, entity, version)

        await self.db.commit()
        await self.db.refresh(entity)
        await self.db.refresh(version)

        await publish_entity_event(
            "updated",
            str(entity_id),
            entity.entity_type,
            str(version_id),
            channel,
            namespace=entity.namespace,
            tags=list(entity.tags or []),
        )
        return entity, version

    async def soft_delete(self, entity_id: uuid.UUID) -> bool:
        """Soft-delete an entity by setting deleted_at."""
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return False

        entity.deleted_at = datetime.now(timezone.utc)
        await delete_entity_search_documents(self.db, entity.entity_id)
        await self.db.commit()

        await publish_entity_event(
            "deleted",
            str(entity_id),
            entity.entity_type,
            namespace=entity.namespace,
            tags=list(entity.tags or []),
        )
        return True

    # ------------------------------------------------------------------
    # CARE library metadata mutations
    # ------------------------------------------------------------------
    #
    # `favourite`, `run_count`, `last_run_at`, `display_name`, `description`
    # are entity-level mutable fields — changing them does NOT create a
    # new version. They power the CARE TUI library (sort by recency,
    # pin favourites, free-form rename). See migration 003 / TODO §1.4.

    async def set_favourite(
        self, entity_id: uuid.UUID, value: bool = True
    ) -> Entity | None:
        """Toggle or set the `favourite` flag on an entity.

        Returns the updated entity, or None if entity is missing or
        soft-deleted.
        """
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return None

        entity.favourite = bool(value)
        await self.db.commit()
        await self.db.refresh(entity)
        await publish_entity_event(
            "favourite_toggled",
            str(entity.entity_id),
            entity.entity_type,
            namespace=entity.namespace,
            tags=list(entity.tags or []),
        )
        return entity

    async def record_run(
        self, entity_id: uuid.UUID, run_id: str | None = None
    ) -> Entity | None:
        """Record that an entity was executed: bump ``run_count`` and
        set ``last_run_at = now()``.

        ``run_id`` is accepted for forthcoming idempotency (a Redis LRU
        of recent run_ids will dedupe accidental double-bumps) but is
        currently a documentation slot only — TODO §1.4 in-memory LRU.

        Returns the updated entity, or None if entity is missing or
        soft-deleted.
        """
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return None

        entity.run_count = (entity.run_count or 0) + 1
        entity.last_run_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(entity)
        await publish_entity_event(
            "run_recorded",
            str(entity.entity_id),
            entity.entity_type,
            namespace=entity.namespace,
            tags=list(entity.tags or []),
        )
        return entity

    async def update_metadata(
        self,
        entity_id: uuid.UUID,
        *,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        favourite: bool | None = None,
    ) -> Entity | None:
        """Partial update of CARE-mutable entity fields.

        Each parameter is applied only when explicitly provided (use
        ``None`` to skip). Does NOT create a new entity version — these
        fields are entity-level mutable slots, not content. Returns the
        updated entity, or None if entity is missing or soft-deleted.
        """
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return None

        mutated = False
        if display_name is not None:
            entity.display_name = display_name[:200]
            mutated = True
        if description is not None:
            entity.description = description
            mutated = True
        if tags is not None:
            entity.tags = list(tags)
            mutated = True
        if favourite is not None:
            entity.favourite = bool(favourite)
            mutated = True

        await self.db.commit()
        await self.db.refresh(entity)
        # Only emit when at least one field actually changed — a PATCH
        # with all-None kwargs is a no-op the library shouldn't react to.
        if mutated:
            await publish_entity_event(
                "metadata_updated",
                str(entity.entity_id),
                entity.entity_type,
                namespace=entity.namespace,
                tags=list(entity.tags or []),
            )
        return entity

    async def list_versions(
        self,
        entity_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[EntityVersion]:
        """List versions for an entity with pagination."""
        stmt = (
            select(EntityVersion)
            .where(EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_entities(
        self,
        entity_type: str,
        channel: str,
        limit: int = 100,
        cursor: str | None = None,
        offset: int = 0,
        *,
        sort_by: str = "created_at",
        sort_dir: str = "asc",
        favourites_only: bool = False,
        tags: list[str] | None = None,
        q: str | None = None,
        namespace: str | None = None,
    ) -> tuple[list[tuple[Entity, EntityVersion]], str | None, bool]:
        """List entities of a specific type for an exact channel using keyset or offset pagination.

        New CARE-library knobs (P0 §1.4):
          * ``sort_by``       — ``"created_at"`` (default) / ``"last_run_at"``
                                 / ``"run_count"`` / ``"display_name"``.
          * ``sort_dir``      — ``"asc"`` (default) / ``"desc"``.
          * ``favourites_only`` — restrict to ``favourite = TRUE``.
          * ``tags``          — restrict to entities whose ``tags`` JSONB
                                 array contains ALL listed tokens
                                 (PostgreSQL ``?&`` operator).
          * ``q``             — case-insensitive substring match across
                                 ``display_name``, ``name``, and
                                 ``description``.
          * ``namespace``     — restrict to a single CARE namespace.

        Cursor pagination only works for the default sort
        (``created_at`` asc); other sort variants force offset
        pagination (cursor is silently ignored).
        """
        stmt = select(Entity).where(
            Entity.entity_type == entity_type,
            Entity.deleted_at.is_(None),
            Entity.channels.op("?")(channel),
        )

        if favourites_only:
            stmt = stmt.where(Entity.favourite.is_(True))
        if namespace is not None:
            stmt = stmt.where(Entity.namespace == namespace)
        if tags:
            stmt = stmt.where(Entity.tags.op("?&")(list(tags)))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Entity.display_name.ilike(like),
                    Entity.name.ilike(like),
                    Entity.description.ilike(like),
                )
            )

        default_sort = sort_by == "created_at" and sort_dir.lower() == "asc"

        if cursor is not None and default_sort:
            cursor_created_at, cursor_entity_id = _decode_cursor(
                cursor,
                entity_type=entity_type,
                channel=channel,
            )
            stmt = stmt.where(
                or_(
                    Entity.created_at > cursor_created_at,
                    and_(
                        Entity.created_at == cursor_created_at,
                        Entity.entity_id > cursor_entity_id,
                    ),
                )
            )

        sort_column_map = {
            "created_at": Entity.created_at,
            "last_run_at": Entity.last_run_at,
            "run_count": Entity.run_count,
            "display_name": Entity.display_name,
        }
        sort_column = sort_column_map.get(sort_by, Entity.created_at)
        descending = sort_dir.lower() == "desc"
        primary = sort_column.desc().nullslast() if descending else sort_column.asc()
        stmt = (
            stmt.order_by(primary, Entity.entity_id.asc())
            .offset(offset)
            .limit(limit + 1)
        )

        result = await self.db.execute(stmt)
        entities = list(result.scalars().all())
        has_more = len(entities) > limit
        page_entities = entities[:limit]

        if not page_entities:
            return [], None, False

        version_ids = [uuid.UUID(entity.channels[channel]) for entity in page_entities]
        versions_result = await self.db.execute(
            select(EntityVersion).where(EntityVersion.version_id.in_(version_ids))
        )
        versions_by_id = {
            version.version_id: version for version in versions_result.scalars().all()
        }

        items: list[tuple[Entity, EntityVersion]] = []
        for entity in page_entities:
            version_id = uuid.UUID(entity.channels[channel])
            version = versions_by_id.get(version_id)
            if version is None:
                raise RuntimeError(
                    f"Entity {entity.entity_id} references missing version {version_id}"
                )
            items.append((entity, version))

        next_cursor = None
        # Only emit a cursor for the default sort — the cursor encoding
        # depends on `(created_at, entity_id)` and is meaningless once
        # the ORDER BY changes shape.
        if has_more and default_sort:
            last_entity = page_entities[-1]
            next_cursor = _encode_cursor(
                last_entity.created_at,
                last_entity.entity_id,
                entity_type,
                channel,
            )

        return items, next_cursor, has_more

    async def get_version(
        self, version_id: uuid.UUID
    ) -> EntityVersion | None:
        """Get a specific version by ID."""
        stmt = select(EntityVersion).where(EntityVersion.version_id == version_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_lineage(
        self,
        entity_id: uuid.UUID,
        *,
        channel: str = "latest",
        version_id: uuid.UUID | None = None,
        max_depth: int = 10,
    ) -> dict | None:
        """Walk the ancestry DAG of a single entity version.

        BFS through ``entity_versions.parents``. Starts from the
        version pinned to ``channel`` on the entity (when ``version_id``
        is None) or the explicit ``version_id``. Returns ``None`` if
        the entity or its starting version can't be resolved.

        The result dict matches :class:`LineageResponse`:
        ``{"entity_id", "root_version_id", "versions": [...],
        "max_depth_reached": bool}`` where each version entry carries
        its own ``parents`` list so callers can rebuild the DAG.
        De-duplicated by ``version_id`` (a multi-parent crossover only
        shows up once).
        """
        # Resolve the starting version.
        if version_id is None:
            entity_result = await self.get_entity(entity_id, channel)
            if entity_result is None:
                return None
            _, start_version = entity_result
            start_version_id = start_version.version_id
        else:
            start_version = await self.get_version(version_id)
            if start_version is None or start_version.entity_id != entity_id:
                return None
            start_version_id = version_id

        # BFS layer-by-layer through `parents`.
        visited: dict[uuid.UUID, EntityVersion] = {start_version_id: start_version}
        depth_of: dict[uuid.UUID, int] = {start_version_id: 0}
        frontier: list[uuid.UUID] = list(start_version.parents or [])
        for d in range(1, max_depth + 1):
            if not frontier:
                break
            # Avoid re-fetching visited nodes.
            to_fetch = [vid for vid in frontier if vid not in visited]
            if not to_fetch:
                break

            stmt = select(EntityVersion).where(EntityVersion.version_id.in_(to_fetch))
            res = await self.db.execute(stmt)
            fetched = list(res.scalars().all())

            next_frontier: list[uuid.UUID] = []
            for ver in fetched:
                visited[ver.version_id] = ver
                depth_of.setdefault(ver.version_id, d)
                for p in (ver.parents or []):
                    if p not in visited:
                        next_frontier.append(p)
            frontier = next_frontier

        # Did we hit the depth cap with more parents left to walk?
        max_depth_reached = bool(frontier)

        # Order: root first, then BFS layers (depth ascending, then by
        # version_number desc within a layer for stable presentation).
        ordered = sorted(
            visited.values(),
            key=lambda v: (depth_of[v.version_id], -(v.version_number or 0)),
        )
        versions_payload = [
            {
                "version_id": str(v.version_id),
                "version_number": v.version_number,
                "parents": [str(p) for p in (v.parents or [])],
                "evolution_meta": v.evolution_meta,
                "change_summary": v.change_summary,
                "author": v.author,
                "created_at": v.created_at,
                "depth": depth_of[v.version_id],
            }
            for v in ordered
        ]

        return {
            "entity_id": str(entity_id),
            "root_version_id": str(start_version_id),
            "versions": versions_payload,
            "max_depth_reached": max_depth_reached,
        }

    @staticmethod
    def _extract_objective_value(
        evolution_meta: dict | None, objective: str
    ) -> float | None:
        """Pull a single objective scalar out of ``evolution_meta``.

        ``objective == "fitness_score"`` is a special case: it reads the
        standardised ``fitness_score`` field, falling back to the legacy
        gigaevo-core ``fitness`` alias (matches the precedence
        ``_extract_fitness`` uses for the auto-promoted ``evolved``
        channel).

        Any other ``objective`` looks up
        ``evolution_meta.objectives[<objective>]`` — that's where the
        standardised multi-objective dict lives (e.g.
        ``{"accuracy": 0.91, "latency_ms": 1240}``).

        Returns ``None`` when the value is absent or unparsable; callers
        treat that as "this version doesn't carry the requested
        objective" rather than ``0.0`` (which would be a misleading
        comparison value).
        """
        if not evolution_meta:
            return None
        if objective == "fitness_score":
            raw = evolution_meta.get("fitness_score")
            if raw is None:
                raw = evolution_meta.get("fitness")
        else:
            objectives = evolution_meta.get("objectives")
            if not isinstance(objectives, dict):
                return None
            raw = objectives.get(objective)
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    async def find_versions_beating(
        self,
        entity_id: uuid.UUID,
        *,
        baseline_channel: str = "stable",
        objective: str = "fitness_score",
        limit: int = 50,
        sort_dir: str = "desc",
    ) -> dict | None:
        """Return all versions whose ``objective`` strictly beats the
        baseline channel's pin.

        Powers `GET /v1/chains/{id}/versions/beating`. The CARE use case
        is "show me candidates I could promote to `stable`" — versions
        that scored higher than the currently-blessed one on the chosen
        metric.

        Returns ``None`` if the entity is missing or soft-deleted (the
        router turns that into 404). When the baseline channel isn't
        pinned, or its pinned version doesn't carry the objective, the
        method still returns a structured payload — with
        ``baseline_value=None`` and ``winners=[]`` — so the caller can
        render a useful "no baseline available" state instead of
        guessing the reason from a 404.

        Strict ``>`` comparison: ties keep the incumbent (matches the
        ``evolved``-channel auto-promotion semantics, so the two
        endpoints describe the same notion of "better").
        """
        # Resolve entity + baseline channel pin.
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return None

        baseline_version_id_str = (entity.channels or {}).get(baseline_channel)
        baseline_version = None
        if baseline_version_id_str:
            try:
                baseline_uuid = uuid.UUID(baseline_version_id_str)
            except (ValueError, TypeError):
                baseline_uuid = None
            if baseline_uuid is not None:
                baseline_version = await self.get_version(baseline_uuid)

        baseline_value = (
            self._extract_objective_value(baseline_version.evolution_meta, objective)
            if baseline_version is not None
            else None
        )

        # When the baseline can't be valued, there's nothing to compare
        # against — return the structured "ill-defined" payload.
        if baseline_value is None:
            return {
                "entity_id": str(entity_id),
                "baseline_channel": baseline_channel,
                "baseline_version_id": baseline_version_id_str,
                "objective": objective,
                "baseline_value": None,
                "winners": [],
            }

        # Walk every version of the entity. Versions are normally a
        # handful per chain — full scan is fine; pushing the filter
        # into SQL would require a JSONB expression that varies by
        # objective shape.
        stmt = select(EntityVersion).where(EntityVersion.entity_id == entity_id)
        result = await self.db.execute(stmt)
        all_versions = list(result.scalars().all())

        winners_payload: list[dict] = []
        baseline_pinned_id = (
            baseline_version.version_id if baseline_version is not None else None
        )
        for v in all_versions:
            value = self._extract_objective_value(v.evolution_meta, objective)
            if value is None or value <= baseline_value:
                continue
            # Exclude the baseline version itself (defensive; with strict
            # > the baseline can't beat itself anyway).
            if v.version_id == baseline_pinned_id:
                continue
            winners_payload.append({
                "version_id": str(v.version_id),
                "version_number": v.version_number,
                "value": value,
                "delta": value - baseline_value,
                "author": v.author,
                "created_at": v.created_at,
                "change_summary": v.change_summary,
            })

        reverse = sort_dir == "desc"
        winners_payload.sort(key=lambda w: w["value"], reverse=reverse)
        winners_payload = winners_payload[:limit]

        return {
            "entity_id": str(entity_id),
            "baseline_channel": baseline_channel,
            "baseline_version_id": baseline_version_id_str,
            "objective": objective,
            "baseline_value": baseline_value,
            "winners": winners_payload,
        }

    async def diff_versions(
        self, from_version_id: uuid.UUID, to_version_id: uuid.UUID
    ) -> dict | None:
        """Compute JSON Merge Patch between two versions."""
        from_ver = await self.get_version(from_version_id)
        to_ver = await self.get_version(to_version_id)
        if from_ver is None or to_ver is None:
            return None

        patch = jsonpatch.make_patch(from_ver.content_json, to_ver.content_json)
        return {
            "from_version": str(from_version_id),
            "to_version": str(to_version_id),
            "patch": patch.to_string(),
        }

    async def revert(
        self,
        entity_id: uuid.UUID,
        target_version_id: uuid.UUID,
        channel: str = "latest",
    ) -> tuple[Entity, EntityVersion] | None:
        """Revert: create a new version with content from an old version."""
        target_version = await self.get_version(target_version_id)
        if target_version is None or target_version.entity_id != entity_id:
            return None

        return await self.update_entity(
            entity_id=entity_id,
            content=target_version.content_json,
            channel=channel,
            parent_version_id=str(target_version_id),
            change_summary=f"Reverted to version {target_version_id}",
            copy_embedding_from_version_id=target_version_id,
            metadata_source_version_id=target_version_id,
        )

    async def pin_channel(
        self, entity_id: uuid.UUID, channel: str, version_id: str
    ) -> bool:
        """Pin a channel to a specific version."""
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return False

        # Verify version exists
        ver = await self.get_version(uuid.UUID(version_id))
        if ver is None or ver.entity_id != entity_id:
            return False

        channels = dict(entity.channels)
        channels[channel] = version_id
        entity.channels = channels
        await self.db.commit()

        await publish_entity_event(
            "pinned",
            str(entity_id),
            entity.entity_type,
            version_id,
            channel,
            namespace=entity.namespace,
            tags=list(entity.tags or []),
        )
        return True

    async def promote(
        self,
        entity_id: uuid.UUID,
        from_channel: str = "latest",
        to_channel: str = "stable",
    ) -> bool:
        """Promote: copy one channel pointer to another."""
        stmt = select(Entity).where(
            Entity.entity_id == entity_id, Entity.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            return False

        source_version = entity.channels.get(from_channel)
        if source_version is None:
            return False

        channels = dict(entity.channels)
        channels[to_channel] = source_version
        entity.channels = channels
        await self.db.commit()

        await publish_entity_event(
            "promoted",
            str(entity_id),
            entity.entity_type,
            source_version,
            to_channel,
            namespace=entity.namespace,
            tags=list(entity.tags or []),
        )
        return True

    async def _resolve_version(
        self, entity: Entity, channel: str
    ) -> EntityVersion | None:
        """Resolve channel to an actual version for an entity."""
        version_id_str = entity.channels.get(channel)
        if version_id_str is None:
            # Fall back to latest channel, then any available version
            version_id_str = entity.channels.get("latest")
            if version_id_str is None:
                # Get the most recent version
                stmt = (
                    select(EntityVersion)
                    .where(EntityVersion.entity_id == entity.entity_id)
                    .order_by(EntityVersion.created_at.desc())
                    .limit(1)
                )
                result = await self.db.execute(stmt)
                return result.scalar_one_or_none()

        version_id = uuid.UUID(version_id_str)
        stmt = select(EntityVersion).where(EntityVersion.version_id == version_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def clear_all(
        self, entity_type: str | None = None
    ) -> dict[str, int]:
        """Soft-delete all entities, optionally filtered by type.

        Returns:
            Dictionary with counts of deleted entities per type.
        """
        now = datetime.now(timezone.utc)
        counts = {}

        types_to_clear = (
            [entity_type] if entity_type else list(VALID_ENTITY_TYPES.values())
        )

        for etype in types_to_clear:
            stmt = select(Entity).where(
                Entity.entity_type == etype, Entity.deleted_at.is_(None)
            )
            result = await self.db.execute(stmt)
            entities = list(result.scalars().all())

            count = 0
            for entity in entities:
                entity.deleted_at = now
                await delete_entity_search_documents(self.db, entity.entity_id)
                count += 1

                await publish_entity_event("deleted", str(entity.entity_id), etype)

            counts[etype] = count

        await self.db.commit()
        return counts

    async def find_duplicate_pairs(
        self,
        entity_type_singular: str,
        *,
        channel: str = "latest",
        threshold: float = 0.95,
        namespace: str | None = None,
        limit: int = 50,
    ) -> dict | None:
        """Find near-duplicate pairs by cosine similarity of embeddings.

        For each entity of ``entity_type_singular``, resolves the
        ``channel`` pin to a specific version and reads its embedding.
        Performs a self-join in SQL (using pgvector's ``<=>`` cosine
        distance) and returns pairs whose similarity meets
        ``threshold``. Pairs are canonicalised
        (``a.entity_id < b.entity_id``) so each unordered pair shows
        up at most once.

        Returns ``None`` when ``settings.enable_vector_search`` is
        disabled — the router maps that to ``503``. Returns a
        structured empty payload (pairs=[]) when no entities have
        embeddings, which the router serves as a normal 200 so
        callers can treat "no duplicates yet" the same as "no
        duplicates found".
        """
        if not settings.enable_vector_search:
            return None

        # ``e.channels`` is JSONB; ``->>`` returns text; cast to uuid.
        # `e.namespace IS NOT DISTINCT FROM :namespace_param` is the
        # NULL-safe equality we want when the caller passes None.
        filters = [
            "e.entity_type = :entity_type",
            "e.deleted_at IS NULL",
            "ev.embedding IS NOT NULL",
            "(e.channels ->> :channel) IS NOT NULL",
        ]
        params: dict = {
            "entity_type": entity_type_singular,
            "channel": channel,
            "threshold": threshold,
            "limit": limit,
        }
        if namespace is not None:
            filters.append("e.namespace = :namespace")
            params["namespace"] = namespace

        # Self-join the resolved channel-version-per-entity, restrict to
        # pairs where the cosine similarity beats `threshold` and
        # `a.entity_id < b.entity_id` (canonicalisation + drops the
        # trivial self-match).
        stmt = text(
            f"""
            WITH channel_versions AS (
                SELECT
                    e.entity_id,
                    e.namespace,
                    e.name,
                    e.display_name,
                    ev.version_id,
                    ev.embedding
                FROM entities AS e
                JOIN entity_versions AS ev
                  ON ev.version_id = ((e.channels ->> :channel)::uuid)
                WHERE {" AND ".join(filters)}
            )
            SELECT
                a.entity_id::text  AS a_entity_id,
                a.version_id::text AS a_version_id,
                a.name             AS a_name,
                a.display_name     AS a_display_name,
                a.namespace        AS a_namespace,
                b.entity_id::text  AS b_entity_id,
                b.version_id::text AS b_version_id,
                b.name             AS b_name,
                b.display_name     AS b_display_name,
                b.namespace        AS b_namespace,
                (1 - (a.embedding <=> b.embedding))::float AS similarity
            FROM channel_versions a
            JOIN channel_versions b
              ON a.entity_id < b.entity_id
            WHERE (1 - (a.embedding <=> b.embedding)) >= :threshold
            ORDER BY similarity DESC, a.entity_id, b.entity_id
            LIMIT :limit
            """
        )
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        pairs = [
            {
                "entity_a": {
                    "entity_id": row["a_entity_id"],
                    "version_id": row["a_version_id"],
                    "name": row["a_name"],
                    "display_name": row["a_display_name"],
                    "namespace": row["a_namespace"],
                },
                "entity_b": {
                    "entity_id": row["b_entity_id"],
                    "version_id": row["b_version_id"],
                    "name": row["b_name"],
                    "display_name": row["b_display_name"],
                    "namespace": row["b_namespace"],
                },
                "similarity": float(row["similarity"]),
                "suggestion": "merge",
            }
            for row in rows
        ]
        return {
            "entity_type": entity_type_singular,
            "channel": channel,
            "threshold": threshold,
            "pairs": pairs,
        }


def entity_metadata_kwargs(entity: Entity) -> dict:
    """Return the CARE-library response fields for an entity.

    Routers `**spread` this into ``EntityResponse(**...)`` so the five
    library-metadata fields land on every typed response without
    repeating the same boilerplate in each endpoint.
    """
    return {
        "favourite": bool(entity.favourite),
        "run_count": int(entity.run_count or 0),
        "last_run_at": entity.last_run_at,
        "display_name": entity.display_name,
        "description": entity.description,
    }
