"""Derived search-document indexing for rich memory-card retrieval."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.models import Entity, EntitySearchDocument, EntityVersion
from .embedding_service import EmbeddingService
from .vector_utils import serialize_vector


DOCUMENT_KIND_FULL_CARD = "full_card"
DOCUMENT_KIND_DESCRIPTION = "description"
DOCUMENT_KIND_TASK_DESCRIPTION = "task_description"
DOCUMENT_KIND_EXPLANATION_SUMMARY = "explanation_summary"
DOCUMENT_KIND_DESCRIPTION_EXPLANATION_SUMMARY = "description_explanation_summary"
DOCUMENT_KIND_DESCRIPTION_TASK_DESCRIPTION_SUMMARY = (
    "description_task_description_summary"
)

DOCUMENT_KINDS = {
    DOCUMENT_KIND_FULL_CARD,
    DOCUMENT_KIND_DESCRIPTION,
    DOCUMENT_KIND_TASK_DESCRIPTION,
    DOCUMENT_KIND_EXPLANATION_SUMMARY,
    DOCUMENT_KIND_DESCRIPTION_EXPLANATION_SUMMARY,
    DOCUMENT_KIND_DESCRIPTION_TASK_DESCRIPTION_SUMMARY,
}


@dataclass
class DerivedSearchDocument:
    document_kind: str
    text_content: str
    card_id: str
    meta_json: dict[str, Any]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join([_stringify(item) for item in value if _stringify(item)])
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)
    return str(value).strip()


def _explanation_parts(content: dict[str, Any]) -> tuple[str, list[str]]:
    explanation = content.get("explanation")
    if isinstance(explanation, dict):
        summary = _stringify(explanation.get("summary"))
        explanations = [
            _stringify(item)
            for item in explanation.get("explanations", [])
            if _stringify(item)
        ]
        return summary, explanations
    text_value = _stringify(explanation)
    return text_value, ([text_value] if text_value else [])


def _build_full_card_text(content: dict[str, Any]) -> str:
    explanation_summary, explanation_full = _explanation_parts(content)
    parts = [
        f"id: {_stringify(content.get('id'))}",
        f"category: {_stringify(content.get('category'))}",
        f"description: {_stringify(content.get('description'))}",
        f"task_description_summary: {_stringify(content.get('task_description_summary'))}",
        f"task_description: {_stringify(content.get('task_description'))}",
        f"program_id: {_stringify(content.get('program_id'))}",
        f"fitness: {_stringify(content.get('fitness'))}",
        f"strategy: {_stringify(content.get('strategy'))}",
        f"last_generation: {_stringify(content.get('last_generation'))}",
        f"programs: {_stringify(content.get('programs'))}",
        f"aliases: {_stringify(content.get('aliases'))}",
        f"keywords: {_stringify(content.get('keywords'))}",
        f"evolution_statistics: {_stringify(content.get('evolution_statistics'))}",
        f"explanation_summary: {explanation_summary}",
        f"explanation_full: {_stringify(explanation_full)}",
        f"works_with: {_stringify(content.get('works_with'))}",
        f"links: {_stringify(content.get('links'))}",
        f"connected_ideas: {_stringify(content.get('connected_ideas'))}",
        f"usage: {_stringify(content.get('usage'))}",
        f"code: {_stringify(content.get('code'))}",
    ]
    return "\n".join([part for part in parts if part.split(": ", 1)[1]])


def derive_memory_card_search_documents(content: dict[str, Any]) -> list[DerivedSearchDocument]:
    if not isinstance(content, dict):
        return []

    card_id = _stringify(content.get("id")) or ""
    description = _stringify(content.get("description"))
    task_description = _stringify(content.get("task_description"))
    task_description_summary = _stringify(content.get("task_description_summary"))
    explanation_summary, _ = _explanation_parts(content)
    full_card_text = _build_full_card_text(content)

    raw_docs = {
        DOCUMENT_KIND_FULL_CARD: full_card_text,
        DOCUMENT_KIND_DESCRIPTION: description,
        DOCUMENT_KIND_TASK_DESCRIPTION: task_description or task_description_summary,
        DOCUMENT_KIND_EXPLANATION_SUMMARY: explanation_summary,
        DOCUMENT_KIND_DESCRIPTION_EXPLANATION_SUMMARY: "\n".join(
            [part for part in [description, explanation_summary] if part]
        ),
        DOCUMENT_KIND_DESCRIPTION_TASK_DESCRIPTION_SUMMARY: "\n".join(
            [part for part in [description, task_description_summary or task_description] if part]
        ),
    }

    docs: list[DerivedSearchDocument] = []
    for document_kind, text_content in raw_docs.items():
        rendered = _stringify(text_content)
        if not rendered:
            continue
        docs.append(
            DerivedSearchDocument(
                document_kind=document_kind,
                text_content=rendered,
                card_id=card_id,
                meta_json={
                    "card_id": card_id,
                    "snippet": description or rendered.splitlines()[0],
                    "document_kind": document_kind,
                },
            )
        )
    return docs


async def delete_entity_search_documents(
    db: AsyncSession,
    entity_id: uuid.UUID,
) -> None:
    await db.execute(
        delete(EntitySearchDocument).where(EntitySearchDocument.entity_id == entity_id)
    )


async def sync_entity_search_documents(
    db: AsyncSession,
    entity: Entity,
    version: EntityVersion,
) -> None:
    await db.execute(
        delete(EntitySearchDocument).where(
            EntitySearchDocument.entity_id == entity.entity_id,
            EntitySearchDocument.version_id == version.version_id,
        )
    )

    if entity.entity_type != "memory_card":
        return

    documents = derive_memory_card_search_documents(version.content_json or {})
    if not documents:
        return

    rows: list[EntitySearchDocument] = []
    for document in documents:
        row = EntitySearchDocument(
            entity_id=entity.entity_id,
            version_id=version.version_id,
            entity_type=entity.entity_type,
            namespace=entity.namespace,
            document_kind=document.document_kind,
            card_id=document.card_id or None,
            text_content=document.text_content,
            meta_json=document.meta_json,
        )
        db.add(row)
        rows.append(row)

    await db.flush()

    if not settings.enable_vector_search or not rows:
        return

    embedding_service = await EmbeddingService.create()
    embeddings = await embedding_service.embed_batch(
        [row.text_content for row in rows]
    )
    for row, embedding in zip(rows, embeddings):
        await db.execute(
            text(
                """
                UPDATE entity_search_documents
                SET embedding = CAST(:embedding AS vector)
                WHERE document_id = :document_id
                """
            ),
            {
                "document_id": row.document_id,
                "embedding": serialize_vector(embedding),
            },
        )
