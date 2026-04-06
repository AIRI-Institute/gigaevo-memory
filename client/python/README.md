# gigaevo-memory

Python client for the GigaEvo Memory Module: persistent storage for CARL artifacts such as chains, steps, agents, and memory cards.

`mmar-carl` is a required dependency and is installed automatically with the client.

## Installation

```bash
pip install gigaevo-memory
```

For vector or hybrid search with the default local embedding provider, also install `sentence-transformers`:

```bash
pip install gigaevo-memory sentence-transformers
```

If you are running against this repository's local Docker stack, bring the API up and apply migrations first:

```bash
make up
make migrate
```

The compose stack in this repository publishes the API at `http://localhost:8002`.
`MemoryClient()` without an explicit `base_url` still defaults to `http://localhost:8000`, which is intended for a standalone local API process or an equivalent reverse-proxied endpoint.

## Quick Start

### Save and load a chain

```python
from mmar_carl import ContextSearchConfig, LLMStepDescription, ReasoningChain
from gigaevo_memory import MemoryClient

chain = ReasoningChain(
    steps=[
        LLMStepDescription(
            number=1,
            title="Analyze text",
            aim="Summarize the input text",
            reasoning_questions="What is the main topic? What are the key points?",
            stage_action="Read the input and produce a concise summary",
            example_reasoning="The text is about X, with key points A, B, and C.",
        )
    ],
    max_workers=1,
    metadata={"name": "Simple Analysis Chain"},
    search_config=ContextSearchConfig(strategy="substring"),
)

with MemoryClient(base_url="http://localhost:8002") as client:
    ref = client.save_chain(
        chain=chain,
        name="simple_analysis_chain",
        tags=["demo", "analysis"],
    )

    loaded_chain = client.get_chain(ref.entity_id, channel="latest")
    loaded_chain_dict = client.get_chain_dict(ref.entity_id, channel="latest")
    versions = client.list_versions(ref.entity_id, entity_type="chain")

    print(ref.entity_id)
    print(len(loaded_chain.steps))
    print(loaded_chain_dict["metadata"]["name"])
    print([v.version_number for v in versions])
```

### Save and search memory cards

```python
from gigaevo_memory import MemoryClient, SearchType

memory_card = {
    "description": "Batch Processing Pattern",
    "explanation": "Use when work can be split into independent chunks.",
    "keywords": ["batch", "parallel", "etl"],
    "category": "pattern_optimization",
}

with MemoryClient(base_url="http://localhost:8002") as client:
    ref = client.save_memory_card(
        memory_card=memory_card,
        name="Batch Processing Pattern",
        tags=memory_card["keywords"],
        when_to_use=memory_card["explanation"],
    )

    card = client.get_memory_card(ref.entity_id)
    results = client.search(
        query="batch processing",
        search_type=SearchType.BM25,
        entity_type="memory_card",
        top_k=5,
    )

    print(card.description)
    print([item.description for item in results])
```

## Search APIs

The client exposes unified search for memory-card retrieval:

- `search(query, search_type=..., top_k=..., entity_type="memory_card")`
  Unified BM25, vector, or hybrid search. Returns `list[MemoryCardSpec]`.

Use unified search for memory-card retrieval:

The following examples use `MemoryClient()` without `base_url`, so they assume a standalone API on `http://localhost:8000` unless you provide a different endpoint.

```python
from gigaevo_memory import MemoryClient, SearchType

with MemoryClient() as client:
    bm25_hits = client.search(
        query="batch processing",
        search_type=SearchType.BM25,
        entity_type="memory_card",
    )

    hybrid_hits = client.search(
        query="performance optimization",
        search_type=SearchType.HYBRID,
        entity_type="memory_card",
        hybrid_weights=(0.3, 0.7),
    )
```

Batch search is also available for memory cards:

```python
from gigaevo_memory import MemoryClient, SearchType

with MemoryClient() as client:
    results = client.batch_search(
        queries=["batch processing", "etl pipeline", "parallel execution"],
        search_type=SearchType.BM25,
        top_k=3,
    )
```

### Vector and hybrid search requirements

Vector-capable search has two runtime requirements:

- The client must be able to generate embeddings.
  By default this means installing `sentence-transformers`, or passing a custom `embedding_provider`.
- The server must have vector search enabled.
  If the API is started with vector search disabled, vector and hybrid requests return `503`.

## Version management

The client includes helpers for versioned entities and channel management:

```python
from gigaevo_memory import MemoryClient

with MemoryClient() as client:
    entity_id = "your-chain-id"
    version_id = "your-version-id"
    from_version = "older-version-id"
    to_version = "newer-version-id"

    versions = client.list_versions(entity_id, entity_type="chain")
    detail = client.get_version(entity_id, version_id, entity_type="chain")
    diff = client.diff_versions(entity_id, from_version, to_version, entity_type="chain")
    client.pin_channel(entity_id, channel="stable", version_id=version_id, entity_type="chain")
    client.promote(entity_id, from_channel="latest", to_channel="stable", entity_type="chain")
```

## Watching for updates

Use `watch_chain()` to subscribe to SSE updates for a chain:

```python
from gigaevo_memory import MemoryClient

with MemoryClient() as client:
    entity_id = "your-chain-id"

    sub = client.watch_chain(
        entity_id,
        callback=lambda new_chain: print(f"Chain updated: {len(new_chain.steps)} steps"),
    )

    # ... later ...
    sub.stop()
```

## Cache policies

```python
from gigaevo_memory import CachePolicy, MemoryClient

# TTL-based cache (default: 300 seconds)
client = MemoryClient(cache_policy=CachePolicy.TTL, cache_ttl=300)

# Conditional GET using ETag when a cached entry exists
client = MemoryClient(cache_policy=CachePolicy.FRESHNESS_CHECK)
```

`CachePolicy.SSE_PUSH` exists as a cache policy enum, but normal entity reads do not automatically attach an SSE listener. For push-style updates today, use `watch_chain()` explicitly.

## Development

```bash
make client-install
make client-test
make client-lint
make client-build
```

## Examples

Runnable example scripts live in [examples/](./examples/):

- `upload_chain.py`
- `download_chain.py`
- `update_chain.py`
- `run_chain.py`
- `upload_memory_card.py`
- `memory_cards_demo.py`
