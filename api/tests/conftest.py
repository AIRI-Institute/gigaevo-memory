"""Integration test fixtures using FastAPI TestClient."""


import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session
from app.main import app


@pytest.fixture
def sample_chain_content():
    """CARL chain content for integration tests."""
    return {
        "version": "1.1",
        "max_workers": 3,
        "enable_progress": False,
        "metadata": {"name": "test_chain"},
        "search_config": {"strategy": "substring"},
        "steps": [
            {
                "number": 1,
                "title": "Analysis",
                "dependencies": [],
                "step_type": "llm",
                "aim": "Analyze input data",
                "reasoning_questions": "",
                "step_context_queries": [],
                "stage_action": "",
                "example_reasoning": "",
            },
            {
                "number": 2,
                "title": "Summary",
                "dependencies": [1],
                "step_type": "llm",
                "aim": "Summarize findings",
                "reasoning_questions": "",
                "step_context_queries": [],
                "stage_action": "",
                "example_reasoning": "",
            },
        ],
    }


@pytest.fixture
def create_chain_body(sample_chain_content):
    """Full request body for creating a chain."""
    return {
        "meta": {
            "name": "integration_test_chain",
            "tags": ["test", "integration"],
            "when_to_use": "Integration testing",
            "author": "test_runner",
        },
        "channel": "latest",
        "content": sample_chain_content,
    }


@pytest_asyncio.fixture
async def async_client():
    """AsyncClient connected to the FastAPI app (no real HTTP)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session():
    """Direct async DB session for integration assertions and test data shaping."""
    async with async_session() as session:
        yield session
