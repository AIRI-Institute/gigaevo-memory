"""
Upload a reasoning chain to GigaEvo Memory.

Usage:
    python upload_chain.py <chain_file.json> [--name "My Chain"] [--tags tag1,tag2]

Environment:
    MEMORY_API_URL - API URL (default: http://localhost:8000)
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gigaevo_memory import MemoryClient


def main():
    default_chain_file = Path(__file__).parent / "chain_v0.json"
    parser = argparse.ArgumentParser(description="Upload a chain to GigaEvo Memory")
    parser.add_argument("chain_file", type=Path, default=default_chain_file, nargs="?", help="Path to chain JSON file (default: chain_v0.json)")
    parser.add_argument("--name", default=None, help="Chain name (default: from file)")
    parser.add_argument("--tags", default=None, help="Comma-separated tags")
    parser.add_argument("--when-to-use", default=None, help="When to use this chain")
    parser.add_argument("--author", default=None, help="Author name")
    parser.add_argument("--channel", default="latest", help="Channel name (default: latest)")
    parser.add_argument("--entity-id", default=None, help="Existing entity ID to update")
    args = parser.parse_args()

    if not args.chain_file.exists():
        print(f"Error: File not found: {args.chain_file}", file=sys.stderr)
        sys.exit(1)

    # Load chain from file
    with open(args.chain_file) as f:
        chain_data = json.load(f)

    # Determine name
    name = args.name or chain_data.get("metadata", {}).get("name", args.chain_file.stem)

    # Parse tags
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    # Connect to Memory API
    api_url = os.getenv("MEMORY_API_URL", "http://localhost:8000")
    client = MemoryClient(base_url=api_url)

    try:
        # Upload chain
        ref = client.save_chain(
            chain=chain_data,
            name=name,
            tags=tags,
            when_to_use=args.when_to_use,
            author=args.author,
            entity_id=args.entity_id,
            channel=args.channel,
        )

        print("✅ Chain uploaded successfully!")
        print(f"   Entity ID: {ref.entity_id}")
        print(f"   Version ID: {ref.version_id}")
        print(f"   Channel: {ref.channel}")

    except Exception as e:
        print(f"❌ Error uploading chain: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
