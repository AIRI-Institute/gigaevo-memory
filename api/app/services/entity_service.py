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

        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            namespace=namespace,
            name=name,
            tags=tags or [],
            when_to_use=when_to_use,
            channels={channel: str(version_id), "latest": str(version_id)},
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
            "created", str(entity_id), entity_type, str(version_id), channel
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
            "updated", str(entity_id), entity.entity_type, str(version_id), channel
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

        await publish_entity_event("deleted", str(entity_id), entity.entity_type)
        return True

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
    ) -> tuple[list[tuple[Entity, EntityVersion]], str | None, bool]:
        """List entities of a specific type for an exact channel using keyset or offset pagination."""
        stmt = select(Entity).where(
            Entity.entity_type == entity_type,
            Entity.deleted_at.is_(None),
            Entity.channels.op("?")(channel),
        )

        if cursor is not None:
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

        stmt = (
            stmt.order_by(Entity.created_at.asc(), Entity.entity_id.asc())
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
        if has_more:
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
            "pinned", str(entity_id), entity.entity_type, version_id, channel
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
            "promoted", str(entity_id), entity.entity_type, source_version, to_channel
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
