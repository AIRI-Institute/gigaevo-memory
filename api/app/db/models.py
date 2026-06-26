"""SQLAlchemy ORM models for entities and entity_versions tables."""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Entity(Base):
    """Stable identity record for a CARL artifact."""

    __tablename__ = "entities"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    namespace: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    when_to_use: Mapped[str | None] = mapped_column(Text)
    channels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # === CARE library metadata (added in migration 003) ===
    # Denormalised fields powering the CARE TUI "My Agents" library
    # (sort by recency / run count, favourite pinning, free-form
    # display_name / description) without paying a per-version JOIN cost.
    favourite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), index=True
    )
    run_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full-text search vector (auto-generated from name and when_to_use)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
        server_default=text("to_tsvector('english', coalesce(name, ''))"),
    )

    versions: Mapped[list["EntityVersion"]] = relationship(
        back_populates="entity",
        order_by="EntityVersion.created_at.desc()",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_entities_tags", "tags", postgresql_using="gin"),
        Index(
            "ix_entities_type_created_entity_id_active",
            "entity_type",
            "created_at",
            "entity_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_entities_channels_active",
            "channels",
            postgresql_using="gin",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # GIN index for full-text search
        Index(
            "ix_entities_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        # Composite index for CARE library listing (mig 003 — kept for
        # `favourites_only` callers + `namespace`-only filters).
        Index(
            "ix_entities_library_listing",
            "namespace",
            "favourite",
            "last_run_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Partial composite matching the planner's preferred scan
        # direction for the default CARE library ORDER BY:
        # `WHERE namespace = ? AND deleted_at IS NULL
        #   ORDER BY last_run_at DESC NULLS LAST, entity_id ASC`
        # Shipped in migration 005 — lets paginated listings under
        # 10k+ entities read a narrow index range instead of sort.
        Index(
            "ix_entities_library_sort",
            "namespace",
            text("last_run_at DESC NULLS LAST"),
            "entity_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ApiKey(Base):
    """API-key principal used by `require_api_key` to authenticate
    incoming requests.

    Stores the **hash** of the key, never the key itself. Plaintext
    keys are only ever returned once at creation time
    (`ApiKeyService.create_key`); subsequent operations work with
    `key_id`s (UUIDs) or hashes.
    """

    __tablename__ = "api_keys"

    key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntityVersion(Base):
    """Immutable snapshot of entity content."""

    __tablename__ = "entity_versions"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(
        nullable=False, default=0
    )
    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    meta_json: Mapped[dict | None] = mapped_column(JSONB)
    parents: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    change_summary: Mapped[str | None] = mapped_column(Text)
    evolution_meta: Mapped[dict | None] = mapped_column(JSONB)
    author: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    entity: Mapped["Entity"] = relationship(back_populates="versions")


class EntitySearchDocument(Base):
    """Derived search document indexed from a specific entity version."""

    __tablename__ = "entity_search_documents"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entity_versions.version_id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    namespace: Mapped[str | None] = mapped_column(String(255), index=True)
    document_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    card_id: Mapped[str | None] = mapped_column(String(255), index=True)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    meta_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_entity_search_documents_entity_version_kind",
            "entity_id",
            "version_id",
            "document_kind",
            unique=True,
        ),
        Index(
            "ix_entity_search_documents_lookup",
            "entity_type",
            "namespace",
            "document_kind",
        ),
        Index(
            "ix_entity_search_documents_meta",
            "meta_json",
            postgresql_using="gin",
        ),
    )
