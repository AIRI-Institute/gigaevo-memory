"""Tests for memory card operations in MemoryClient."""

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from gigaevo_memory import MemoryClient
from gigaevo_memory.models import MemoryCardSpec, EntityRef


@pytest.fixture
def client():
    return MemoryClient(base_url="http://test-api:8000")


@pytest.fixture
def sample_memory_card_spec():
    return MemoryCardSpec(
        id="memory-card-123",
        category="testing",
        task_description="Test task",
        description="Test memory card",
        explanation="For testing",
        strategy="exploration",
        keywords=["test", "memory"],
        works_with=[],
        links=[]
    )


class TestGetMemoryCard:
    def test_get_memory_card_success(self, client, sample_memory_card_spec):
        response = {
            "entity_type": "memory_card",
            "entity_id": "card-id-123",
            "version_id": "ver-456",
            "channel": "latest",
            "etag": "abc123",
            "meta": {"name": "test_card"},
            "content": sample_memory_card_spec.model_dump(mode="json")
        }
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/memory-cards/card-id-123").mock(
                return_value=httpx.Response(200, json=response)
            )
            card = client.get_memory_card("card-id-123")
        
        assert isinstance(card, MemoryCardSpec)
        assert card.id == "memory-card-123"


class TestSaveMemoryCard:
    def test_save_memory_card_create(self, client, sample_memory_card_spec):
        response = {
            "entity_type": "memory_card",
            "entity_id": "new-card-id",
            "version_id": "ver-1",
            "channel": "latest",
            "etag": "abc",
            "meta": {"name": "test_card"},
            "content": sample_memory_card_spec.model_dump(mode="json")
        }
        
        with respx.mock:
            respx.post("http://test-api:8000/v1/memory-cards").mock(
                return_value=httpx.Response(201, json=response)
            )
            ref = client.save_memory_card(
                sample_memory_card_spec,
                name="test_card",
                tags=["test"]
            )
        
        assert isinstance(ref, EntityRef)
        assert ref.entity_id == "new-card-id"

    def test_save_memory_card_dict_normalizes_nested_models(self, client):
        class ConnectedIdea(BaseModel):
            idea_id: str
            description: str

        response = {
            "entity_type": "memory_card",
            "entity_id": "new-card-id",
            "version_id": "ver-1",
            "channel": "latest",
            "etag": "abc",
            "meta": {"name": "test_card"},
            "content": {"id": "memory-card-123", "description": "Test memory card"},
        }

        with respx.mock:
            route = respx.post("http://test-api:8000/v1/memory-cards").mock(
                return_value=httpx.Response(201, json=response)
            )
            ref = client.save_memory_card(
                {
                    "id": "memory-card-123",
                    "description": "Test memory card",
                    "connected_ideas": [
                        ConnectedIdea(idea_id="idea-1", description="mutual information"),
                    ],
                },
                name="test_card",
                tags=["test"],
            )

        assert isinstance(ref, EntityRef)
        assert ref.entity_id == "new-card-id"
        assert len(route.calls) == 1

        payload = json.loads(route.calls[0].request.content.decode("utf-8"))
        assert payload["content"]["connected_ideas"] == [
            {"idea_id": "idea-1", "description": "mutual information"}
        ]


class TestBatchDownload:
    def test_batch_download_basic(self, client):
        response = [
            {
                "entity_type": "memory_card",
                "entity_id": f"card-{i}",
                "version_id": "ver-1",
                "channel": "latest",
                "etag": "abc",
                "meta": {"name": f"Card {i}"},
                "content": {"id": f"card-{i}", "description": f"Card {i}"}
            }
            for i in range(3)
        ]
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/memory-cards").mock(
                return_value=httpx.Response(200, json=response)
            )
            batches = list(client.batch_download(batch_size=10))
        
        assert len(batches) == 1
        assert len(batches[0]) == 3
        assert all(isinstance(c, MemoryCardSpec) for c in batches[0])

    def test_batch_download_with_size_limit(self, client):
        response = [
            {
                "entity_type": "memory_card",
                "entity_id": f"card-{i}",
                "version_id": "ver-1",
                "channel": "latest",
                "etag": "abc",
                "meta": {"name": f"Card {i}"},
                "content": {"id": f"card-{i}", "description": f"Card {i}"}
            }
            for i in range(5)
        ]
        
        with respx.mock:
            respx.get("http://test-api:8000/v1/memory-cards").mock(
                return_value=httpx.Response(200, json=response)
            )
            batches = list(client.batch_download(batch_size=10, size_limit=3))
        
        total_cards = sum(len(batch) for batch in batches)
        assert total_cards == 3

    def test_batch_download_empty_response(self, client):
        with respx.mock:
            respx.get("http://test-api:8000/v1/memory-cards").mock(
                return_value=httpx.Response(200, json=[])
            )
            batches = list(client.batch_download())
        
        assert len(batches) == 0
