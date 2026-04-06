"""Test fixtures for the gigaevo-memory client."""

import pytest


@pytest.fixture
def sample_chain_dict():
    """A sample CARL chain dict matching chain_to_content() output."""
    return {
        "version": "1.1",
        "max_workers": 3,
        "enable_progress": False,
        "metadata": {"name": "fin_triage_v2", "domain": "finance"},
        "search_config": {"strategy": "substring", "substring_config": {"case_sensitive": False}},
        "steps": [
            {
                "number": 1,
                "title": "Financial Metrics Extraction",
                "dependencies": [],
                "step_type": "llm",
                "aim": "Extract and organize key financial metrics from the report",
                "reasoning_questions": "What are the main financial figures?",
                "step_context_queries": [
                    {"query": "Revenue", "search_strategy": "substring", "search_config": {"case_sensitive": False}},
                    "Profit",
                ],
                "stage_action": "Identify and list all financial metrics",
                "example_reasoning": "Revenue of $2.5M with 15% growth",
                "step_config": None,
                "llm_config": {"model": "openai/gpt-4o", "temperature": 0.2, "endpoint_key": None, "max_tokens": None},
            },
            {
                "number": 2,
                "title": "Store Analysis Result",
                "dependencies": [1],
                "step_type": "memory",
                "step_config": {
                    "operation": "write",
                    "memory_key": "analysis_result",
                    "value_source": "$history[-1]",
                    "default_value": None,
                    "namespace": "default",
                },
            },
            {
                "number": 3,
                "title": "Risk Assessment",
                "dependencies": [1],
                "step_type": "llm",
                "aim": "Identify and assess challenges and risks",
                "reasoning_questions": "What challenges exist?",
                "step_context_queries": ["Challenges"],
                "stage_action": "Analyze each challenge",
                "example_reasoning": "Supply chain issues may affect delivery",
                "step_config": None,
                "llm_config": {"model": None, "temperature": None, "endpoint_key": "fast_model", "max_tokens": None},
            },
            {
                "number": 4,
                "title": "Executive Summary",
                "dependencies": [2, 3],
                "step_type": "llm",
                "aim": "Synthesize findings into actionable executive summary",
                "reasoning_questions": "What are the key takeaways?",
                "step_context_queries": [],
                "stage_action": "Create concise summary",
                "example_reasoning": "Strong financial performance suggests focus on supply chain",
                "step_config": None,
                "llm_config": None,
            },
        ],
    }


@pytest.fixture
def sample_step_dict():
    """A sample tool step dict."""
    return {
        "number": 1,
        "title": "Fetch Financial Data",
        "dependencies": [],
        "step_type": "tool",
        "step_config": {
            "tool_name": "fetch_data",
            "tool_description": "Fetch data from external API",
            "parameters": [],
            "input_mapping": {"url": "$metadata.api_url"},
            "output_key": "result",
            "timeout": 30.0,
            "retry_on_error": True,
        },
    }


@pytest.fixture
def sample_agent_dict():
    """A sample agent dict."""
    return {
        "name": "support_bot_v3",
        "description": "Customer support agent with financial analysis capabilities",
        "chain_ref": {
            "entity_id": "550e8400-e29b-41d4-a716-446655440000",
            "entity_type": "chain",
            "channel": "stable",
        },
        "system_prompt": "You are a helpful financial analyst.",
        "default_model": "gpt-4o",
        "max_workers": 3,
        "tool_manifests": [
            {"name": "calculate_growth", "description": "Calculate revenue growth"},
        ],
        "tags": ["finance", "support"],
        "when_to_use": "Customer financial queries",
    }


@pytest.fixture
def sample_memory_card_dict():
    """A sample memory card dict."""
    return {
        "name": "Multi-step Financial Analysis",
        "description": "Pattern for analyzing financial documents in stages",
        "when_to_use": "When processing complex financial reports with multiple sections",
        "tags": ["finance", "analysis", "multi-step"],
        "related_entities": [
            {
                "entity_id": "550e8400-e29b-41d4-a716-446655440000",
                "entity_type": "chain",
            },
        ],
        "examples": ["Q4 report analysis", "Annual review processing"],
        "anti_patterns": ["Single-step monolithic analysis"],
        "provenance": {"source": "best_practices", "version": "1.0"},
    }


@pytest.fixture
def sample_entity_response(sample_chain_dict):
    """A sample entity response from the API."""
    return {
        "entity_type": "chain",
        "entity_id": "550e8400-e29b-41d4-a716-446655440000",
        "version_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "channel": "latest",
        "etag": "abc123",
        "meta": {
            "name": "fin_triage_v2",
            "tags": ["finance"],
            "when_to_use": "Financial analysis",
            "author": "alice",
        },
        "content": sample_chain_dict,
    }


@pytest.fixture
def sample_version_info():
    """A sample version info response."""
    return {
        "version_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "entity_id": "550e8400-e29b-41d4-a716-446655440000",
        "version_number": 1,
        "author": "alice",
        "change_summary": "Initial version",
        "evolution_meta": None,
        "parents": None,
        "created_at": "2026-02-12T00:00:00Z",
    }
