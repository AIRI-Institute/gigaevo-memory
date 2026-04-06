"""Initial schema: entities and entity_versions tables.

Revision ID: 001
Revises: None
Create Date: 2026-03-17
Updated: 2026-03-20 (merged version_number column)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.config import settings

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- entities table ---
    op.create_table(
        "entities",
        sa.Column("entity_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("namespace", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tags", JSONB, nullable=False, server_default="[]"),
        sa.Column("when_to_use", sa.Text, nullable=True),
        sa.Column("channels", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index("ix_entities_namespace", "entities", ["namespace"])
    op.create_index(
        "ix_entities_tags", "entities", ["tags"], postgresql_using="gin"
    )
    op.create_index(
        "ix_entities_type_created_entity_id_active",
        "entities",
        ["entity_type", "created_at", "entity_id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_entities_channels_active",
        "entities",
        ["channels"],
        unique=False,
        postgresql_using="gin",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Full-text search: stored generated column + GIN index
    op.execute(
        """
        ALTER TABLE entities
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(name, '') || ' ' || coalesce(when_to_use, ''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_entities_search_vector ON entities USING GIN (search_vector)"
    )

    # --- entity_versions table (with version_number from the start) ---
    op.create_table(
        "entity_versions",
        sa.Column("version_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("entities.entity_id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_json", JSONB, nullable=False),
        sa.Column("meta_json", JSONB, nullable=True),
        sa.Column("parents", sa.ARRAY(UUID(as_uuid=True)), nullable=True),
        sa.Column("change_summary", sa.Text, nullable=True),
        sa.Column("evolution_meta", JSONB, nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_entity_versions_entity_id", "entity_versions", ["entity_id"]
    )
    # pgvector's ivfflat index requires a fixed-dimension vector column.
    op.execute(
        f"ALTER TABLE entity_versions ADD COLUMN embedding vector({settings.vector_dimension})"
    )

    # IVFFLAT index for faster vector similarity search (requires ~1000+ rows for optimal performance)
    op.execute(
        """
        CREATE INDEX ix_entity_versions_embedding_ivfflat
        ON entity_versions
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_entity_versions_embedding_ivfflat")
    op.execute("ALTER TABLE entity_versions DROP COLUMN embedding")
    op.drop_index("ix_entity_versions_entity_id", table_name="entity_versions")
    op.drop_table("entity_versions")
    op.drop_index("ix_entities_channels_active", table_name="entities")
    op.drop_index("ix_entities_type_created_entity_id_active", table_name="entities")
    op.drop_index("ix_entities_search_vector", table_name="entities")
    op.drop_index("ix_entities_tags", table_name="entities")
    op.drop_index("ix_entities_namespace", table_name="entities")
    op.drop_index("ix_entities_entity_type", table_name="entities")
    op.drop_table("entities")
