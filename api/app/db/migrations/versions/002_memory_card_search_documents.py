"""Add derived search documents for field-specific memory-card retrieval.

Revision ID: 002
Revises: 001
Create Date: 2026-03-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.config import settings

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_search_documents",
        sa.Column("document_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("entities.entity_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("entity_versions.version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("namespace", sa.String(255), nullable=True),
        sa.Column("document_kind", sa.String(64), nullable=False),
        sa.Column("card_id", sa.String(255), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("meta_json", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_entity_search_documents_entity_id",
        "entity_search_documents",
        ["entity_id"],
    )
    op.create_index(
        "ix_entity_search_documents_version_id",
        "entity_search_documents",
        ["version_id"],
    )
    op.create_index(
        "ix_entity_search_documents_document_kind",
        "entity_search_documents",
        ["document_kind"],
    )
    op.create_index(
        "ix_entity_search_documents_card_id",
        "entity_search_documents",
        ["card_id"],
    )
    op.create_index(
        "ix_entity_search_documents_entity_version_kind",
        "entity_search_documents",
        ["entity_id", "version_id", "document_kind"],
        unique=True,
    )
    op.create_index(
        "ix_entity_search_documents_lookup",
        "entity_search_documents",
        ["entity_type", "namespace", "document_kind"],
    )
    op.create_index(
        "ix_entity_search_documents_meta",
        "entity_search_documents",
        ["meta_json"],
        postgresql_using="gin",
    )

    op.execute(
        """
        ALTER TABLE entity_search_documents
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(text_content, ''))
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_entity_search_documents_search_vector
        ON entity_search_documents
        USING GIN (search_vector)
        """
    )

    op.execute(
        f"""
        ALTER TABLE entity_search_documents
        ADD COLUMN embedding vector({settings.vector_dimension})
        """
    )
    op.execute(
        """
        CREATE INDEX ix_entity_search_documents_embedding_ivfflat
        ON entity_search_documents
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_entity_search_documents_embedding_ivfflat")
    op.execute("DROP INDEX IF EXISTS ix_entity_search_documents_search_vector")
    op.execute("ALTER TABLE entity_search_documents DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE entity_search_documents DROP COLUMN IF EXISTS search_vector")
    op.drop_index(
        "ix_entity_search_documents_meta",
        table_name="entity_search_documents",
    )
    op.drop_index(
        "ix_entity_search_documents_lookup",
        table_name="entity_search_documents",
    )
    op.drop_index(
        "ix_entity_search_documents_entity_version_kind",
        table_name="entity_search_documents",
    )
    op.drop_index(
        "ix_entity_search_documents_card_id",
        table_name="entity_search_documents",
    )
    op.drop_index(
        "ix_entity_search_documents_document_kind",
        table_name="entity_search_documents",
    )
    op.drop_index(
        "ix_entity_search_documents_version_id",
        table_name="entity_search_documents",
    )
    op.drop_index(
        "ix_entity_search_documents_entity_id",
        table_name="entity_search_documents",
    )
    op.drop_table("entity_search_documents")
