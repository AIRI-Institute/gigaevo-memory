# GigaEvo Memory Client Examples

Scripts for managing CARL reasoning chains in GigaEvo Memory.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed
- GigaEvo Memory API running

If you use this repository's Docker stack, the API is available at `http://localhost:8002`.
The scripts themselves still fall back to `http://localhost:8000` when `MEMORY_API_URL` is unset, which is useful for a standalone local API process.

## Setup

```bash
# Sync the client package and its dev tools into the workspace .venv
uv sync --extra dev

# Run scripts
cd client/python/examples
uv run python upload_chain.py --help
uv run python upload_chain.py chain_v0.json --name "My Chain"
```

## Environment

```bash
export MEMORY_API_URL="http://localhost:8002"  # use this for the repo Docker stack
```

Leave `MEMORY_API_URL` unset only if you are running a standalone API on `http://localhost:8000`.

The example commands below assume you run them via `uv run` from `client/python/examples`, so the
workspace `.venv` and Python 3.12 interpreter are used automatically.

---

## Quick Start: Versioned Chain Workflow

This example shows how to upload a chain, get its ID, update it with a new version, and retrieve it.

### Step 1: Upload chain_v0.json

```bash
python upload_chain.py chain_v0.json --name "Analysis Chain" --tags "analysis,v0"
```

**Output:**
```
✅ Chain uploaded successfully!
   Entity ID: a6a78956-0c23-45ae-af2c-d8be8bb12ddb
   Version ID: e2b15267-f737-411a-8cbd-4b3b182328a5
   Channel: latest
```

**Save the Entity ID** — you'll need it for updates and retrieval.

### Step 2: Retrieve the chain

```bash
# Get chain info
python download_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb --info --validate
```

**Output:**
```
📋 Chain: Simple Analysis Chain
   Entity ID: a6a78956-0c23-45ae-af2c-d8be8bb12ddb
   Channel: latest
   Steps: 1
   Max workers: 1

   Step types:
     - llm: 1

✅ Chain validated successfully
```

### Step 3: Update to chain_v1.json

```bash
python update_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb chain_v1.json \
  --change-summary "Added entity extraction and structured output steps" \
  --promote
```

**Output:**
```
📄 Current chain: Simple Analysis Chain
✅ Chain updated successfully!
   Entity ID: a6a78956-0c23-45ae-af2c-d8be8bb12ddb
   Version ID: 4575ef9b-7bdf-4797-b1ce-3dc189c54759
   Channel: latest
   Promoted to: stable
```

### Step 4: Retrieve the updated chain

```bash
# Get latest version
python download_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb --info

# Get stable version (if promoted)
python download_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb --channel stable --info

# Download to file
python download_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb -o production_chain.json
```

**Output:**
```
📋 Chain: Multi-Step Analysis Chain
   Entity ID: a6a78956-0c23-45ae-af2c-d8be8bb12ddb
   Channel: latest
   Steps: 3
   Max workers: 3

   Step types:
     - llm: 2
     - structured_output: 1
```

### Step 5: Run the chain

```bash
# Run with inline input
python run_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb \
  --input "Artificial intelligence is transforming industries worldwide. Companies like OpenAI and Google are leading the charge." \
  --verbose

# Run with input file
python run_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb \
  --input-file article.txt \
  --output-file analysis.json \
  --validate

# Run stable version in production
python run_chain.py a6a78956-0c23-45ae-af2c-d8be8bb12ddb \
  --channel stable \
  --input "Your text here" \
  -o result.json
```

**Output:**
```
📥 Loading chain a6a78956-0c23-45ae-af2c-d8be8bb12ddb from channel 'latest'...
✅ Chain loaded: 3 steps
🔍 Validating chain...
🚀 Executing chain...
   Max workers: 3
   Steps: ['Analyze text', 'Extract entities', 'Generate report']
{
  "chain_id": "a6a78956-0c23-45ae-af2c-d8be8bb12ddb",
  "channel": "latest",
  "input": "Artificial intelligence is transforming industries...",
  "result": {
    "summary": "The text discusses AI's impact on industries...",
    "sentiment": "positive",
    "entities": {
      "people": [],
      "organizations": ["OpenAI", "Google"],
      "locations": []
    },
    "key_points": [
      "AI is transforming industries worldwide",
      "OpenAI and Google are leading companies"
    ]
  },
  "step_results": {
    "1": {"output": "...", "success": true},
    "2": {"output": "...", "success": true},
    "3": {"output": "...", "success": true}
  },
  "success": true
}
```

---

## Scripts Reference

### upload_chain.py

Upload a new chain to memory:

```bash
python upload_chain.py <chain_file.json> [options]
```

| Option | Description |
|--------|-------------|
| `--name` | Chain name (default: from file metadata or filename) |
| `--tags` | Comma-separated tags |
| `--when-to-use` | Description of when to use this chain |
| `--author` | Author name |
| `--channel` | Channel name (default: `latest`) |
| `--entity-id` | Update existing entity instead of creating new |

### update_chain.py

Update an existing chain:

```bash
python update_chain.py <entity_id> <chain_file.json> [options]
```

| Option | Description |
|--------|-------------|
| `--name` | New chain name |
| `--tags` | New tags (comma-separated) |
| `--channel` | Channel to update (default: `latest`) |
| `--change-summary` | Description of changes |
| `--promote` | Promote to `stable` channel after update |

### download_chain.py

Download a chain for use:

```bash
python download_chain.py <entity_id> [options]
```

| Option | Description |
|--------|-------------|
| `--channel` | Channel to use (default: `latest`) |
| `--output, -o` | Output file path |
| `--print` | Print to stdout |
| `--validate` | Validate chain with CARL before output |
| `--info` | Show chain info without downloading |

### run_chain.py

Execute a chain from memory:

```bash
python run_chain.py <entity_id> [options]
```

| Option | Description |
|--------|-------------|
| `--channel` | Channel to use (default: `latest`) |
| `--input, -i` | Input text for the chain |
| `--input-file` | Read input from file |
| `--output-file, -o` | Write result to file |
| `--validate` | Validate chain before execution |
| `--verbose, -v` | Show detailed execution info |

**Examples:**
```bash
# Basic execution
python run_chain.py abc123 --input "Analyze this text"

# With file I/O
python run_chain.py abc123 --input-file data.txt -o result.json

# Use stable channel
python run_chain.py abc123 --channel stable -i "Your input" -o output.json

# Pipe input
echo "Text to analyze" | python run_chain.py abc123
```

---

## Example Files

| File | Description | Steps | Workers |
|------|-------------|-------|---------|
| `chain_v0.json` | Basic single-step chain | 1 (LLM) | 1 |
| `chain_v1.json` | Enhanced multi-step chain | 3 (2 LLM + 1 structured) | 3 |
| `example_chain.json` | Demo chain with all step types | 3 | 3 |

**Step-by-step breakdown:**

**chain_v0.json** - Basic analysis:
- Step 1: Analyze text (LLM) → returns summary

**chain_v1.json** - Complete analysis pipeline:
- Step 1: Analyze text (LLM) → initial analysis
- Step 2: Extract entities (LLM) → named entities
- Step 3: Generate report (structured_output) → JSON report

**example_chain.json** - All step types demo:
- Step 1: Analyze input (LLM)
- Step 2: Transform data (transform)
- Step 3: Generate output (structured_output)

---

## Channel Workflow

```
┌─────────────┐     update      ┌─────────────┐
│   latest    │ ───────────────▶│   latest    │
│   (v0)      │                 │   (v1)      │
└─────────────┘                 └──────┬──────┘
                                       │
                                       │ promote
                                       ▼
                                ┌─────────────┐
                                │   stable    │
                                │   (v1)      │
                                └─────────────┘
```

**Typical workflow:**
1. Develop and test with `latest` channel
2. When ready for production, use `--promote` to copy to `stable`
3. Production systems use `--channel stable` for reliability
4. Continue development in `latest` without affecting production

---

## Supported Step Types

| Type | Description | Required Config |
|------|-------------|-----------------|
| `llm` | Standard LLM reasoning step | `aim`, `reasoning_questions`, `stage_action`, `example_reasoning` |
| `tool` | External tool/function call | `step_config.tool_name`, `step_config.arguments` |
| `mcp` | Model Context Protocol call | `step_config.server`, `step_config.tool` |
| `memory` | Memory read/write operation | `step_config.operation`, `step_config.key` |
| `transform` | Data transformation | `step_config.transform_type`, `step_config.expression` |
| `conditional` | Conditional branching | `step_config.condition`, `step_config.branches` |
| `structured_output` | Schema-constrained JSON output | `step_config.output_schema` |

---

## Programmatic Usage

```python
import asyncio
import sys
from pathlib import Path

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gigaevo_memory import MemoryClient
from mmar_carl import ChainExecutor, ChainContext

async def main():
    client = MemoryClient(base_url="http://localhost:8002")

    # Upload chain
    ref = client.save_chain(
        chain=chain_dict,
        name="My Chain",
        tags=["production"],
    )
    print(f"Entity ID: {ref.entity_id}")

    # Retrieve chain
    chain = client.get_chain(ref.entity_id, channel="stable")

    # Execute chain
    executor = ChainExecutor(chain)
    context = ChainContext(input_text="Your input text here")
    result = await executor.run(context)

    print(f"Result: {result.final_output}")

    # Access step results
    for step_num, step_result in result.step_results.items():
        print(f"Step {step_num}: {step_result.output}")

    client.close()

asyncio.run(main())
```

---

## Memory Cards Example

### Quick Start Demo

The easiest way to see all memory card operations is to run the comprehensive demo:

```bash
python memory_cards_demo.py
```

This script runs through all operations in sequence:
1. ✅ Creates a new memory card
2. ✅ Retrieves it by ID
3. ✅ Lists all memory cards
4. ✅ BM25 search (full-text)
5. ✅ Vector search (semantic)
6. ✅ Hybrid search (combined)
7. ✅ Batch search (parallel queries)

### Individual Commands

For individual operations, use `memory_cards_example.py`:

The `memory_cards_example.py` script demonstrates complete CRUD and search operations for memory cards.

### Quick Start

```bash
# Create a memory card
python memory_cards_example.py create \
  --description "Map-reduce pattern for distributed processing" \
  --explanation "Use this for large-scale data transformations" \
  --tags "pattern,distributed,performance"

# Get card by ID
python memory_cards_example.py get abc123-def4-5678-90ab-cdef12345678

# List all cards
python memory_cards_example.py list --limit 20

# BM25 search
python memory_cards_example.py search --query "performance" --search-type bm25

# Vector search
python memory_cards_example.py search --query "optimization" --search-type vector

# Hybrid search
python memory_cards_example.py search --query "data analysis" --search-type hybrid \
  --bm25-weight 0.3 --vector-weight 0.7

# Batch search demo
python memory_cards_example.py batch-demo
```

### Quick Start with Sample Card

```bash
# Upload the sample memory card
python upload_memory_card.py memory_card_sample.json \
  --name "Map-Reduce Pattern" \
  --tags "pattern,distributed,performance"

# The sample card demonstrates:
# - Map-reduce pattern for distributed processing
# - Evolution statistics (gain, quartile, survival)
# - Usage statistics (retrieval count, fitness impact)
# - Related cards (works_with, links)
# - Example scenarios
```

### Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `create` | Create a new memory card | `python memory_cards_example.py create --description "Pattern" --explanation "When to use it" --tags "tag1,tag2"` |
| `get` | Get card by ID | `python memory_cards_example.py get <card_id>` |
| `list` | List all cards | `python memory_cards_example.py list --limit 50` |
| `search` | Search cards | `python memory_cards_example.py search --query "performance" --search-type hybrid` |
| `batch-demo` | Demonstrate batch search | `python memory_cards_example.py batch-demo` |

### Search Types

**BM25 Search** - Full-text search using keywords:
```bash
python memory_cards_example.py search \
  --query "data processing" \
  --search-type bm25 \
  --top-k 10
```

**Vector Search** - Semantic search using embeddings:
```bash
python memory_cards_example.py search \
  --query "efficient computation" \
  --search-type vector \
  --top-k 10
```

**Hybrid Search** - Combined BM25 + Vector with configurable weights:
```bash
python memory_cards_example.py search \
  --query "performance optimization" \
  --search-type hybrid \
  --bm25-weight 0.3 \
  --vector-weight 0.7 \
  --top-k 10
```

### Programmatic Usage

```python
from gigaevo_memory import MemoryClient, SearchType

client = MemoryClient(base_url="http://localhost:8002")

# Create a memory card
ref = client.save_memory_card(
    memory_card={
        "description": "Map-reduce pattern",
        "explanation": "Use for distributed data processing",
        "keywords": ["pattern", "distributed"],
        "category": "pattern_optimization",
    },
    name="Map-Reduce Pattern",
    tags=["pattern", "performance"],
)

# Get card by ID
card = client.get_memory_card_dict(ref.entity_id)
print(f"Card: {card['description']}")

# List all cards
cards = client.list_memory_cards(limit=100)
for card in cards:
    print(f"- {card.meta.get('name', 'N/A')}")

# BM25 search
results = client.search(
    query="performance optimization",
    search_type=SearchType.BM25,
    top_k=10,
)

# Vector search
results = client.search(
    query="efficient computation",
    search_type=SearchType.VECTOR,
    top_k=10,
)

# Hybrid search
results = client.search(
    query="data analysis",
    search_type=SearchType.HYBRID,
    top_k=10,
    hybrid_weights=(0.3, 0.7),  # BM25=30%, Vector=70%
)

# Batch search
queries = ["performance", "optimization", "analysis"]
results = client.batch_search(
    queries=queries,
    search_type=SearchType.HYBRID,
    top_k=5,
)
for query, cards in zip(queries, results):
    print(f"{query}: {len(cards)} results")

client.close()
```

---

## Troubleshooting
