"""
Update an existing chain version in GigaEvo Memory.

Usage:
    python update_chain.py <entity_id> <chain_file.json> [--change-summary "Fixed step 2"]

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
    parser = argparse.ArgumentParser(description="Update a chain in GigaEvo Memory")
    parser.add_argument("entity_id", help="Entity ID to update")
    parser.add_argument("chain_file", type=Path, help="Path to updated chain JSON file")
    parser.add_argument("--name", default=None, help="New chain name")
    parser.add_argument("--tags", default=None, help="Comma-separated tags")
    parser.add_argument("--when-to-use", default=None, help="When to use this chain")
    parser.add_argument("--author", default=None, help="Author name")
    parser.add_argument("--channel", default="latest", help="Channel to update (default: latest)")
    parser.add_argument("--change-summary", default=None, help="Description of changes")
    parser.add_argument("--promote", action="store_true", help="Promote to 'stable' after update")
    args = parser.parse_args()

    if not args.chain_file.exists():
        print(f"Error: File not found: {args.chain_file}", file=sys.stderr)
        sys.exit(1)

    # Load chain from file
    with open(args.chain_file) as f:
        chain_data = json.load(f)

    # Parse tags
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None

    # Connect to Memory API
    api_url = os.getenv("MEMORY_API_URL", "http://localhost:8000")
    client = MemoryClient(base_url=api_url)

    try:
        # Get current chain to check it exists
        current = client.get_chain_dict(args.entity_id, channel=args.channel)
        current_name = current.get("metadata", {}).get("name", "Unknown")
        print(f"📄 Current chain: {current_name}")

        # Update chain
        ref = client.save_chain(
            chain=chain_data,
            name=args.name or current_name,
            tags=tags,
            when_to_use=args.when_to_use,
            author=args.author,
            entity_id=args.entity_id,
            channel=args.channel,
            evolution_meta={"change_summary": args.change_summary} if args.change_summary else None,
        )

        print("✅ Chain updated successfully!")
        print(f"   Entity ID: {ref.entity_id}")
        print(f"   Version ID: {ref.version_id}")
        print(f"   Channel: {ref.channel}")

        if args.promote:
            # Promote to stable
            import httpx
            resp = httpx.post(
                f"{api_url}/v1/chains/{args.entity_id}/promote",
                params={"from_channel": args.channel, "to_channel": "stable"},
            )
            if resp.status_code == 200:
                print("   Promoted to: stable")
            else:
                print(f"   ⚠️ Failed to promote: {resp.text}", file=sys.stderr)

    except Exception as e:
        print(f"❌ Error updating chain: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
