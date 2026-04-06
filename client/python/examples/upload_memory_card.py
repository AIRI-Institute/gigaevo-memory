"""
Upload a memory card to GigaEvo Memory from JSON file.

Usage:
    python upload_memory_card.py [memory_card.json] [--name "My Card"] [--tags tag1,tag2]

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
    default_file = Path(__file__).parent / "memory_card_sample.json"
    parser = argparse.ArgumentParser(description="Upload a memory card to GigaEvo Memory")
    parser.add_argument("card_file", type=Path, default=default_file, nargs="?",
                       help=f"Path to memory card JSON file (default: {default_file.name})")
    parser.add_argument("--name", help="Card name (default: from file)")
    parser.add_argument("--tags", help="Comma-separated tags (overrides file)")
    parser.add_argument("--author", help="Author name")
    parser.add_argument("--channel", default="latest", help="Channel name")
    parser.add_argument("--entity-id", help="Existing entity ID to update")
    args = parser.parse_args()

    if not args.card_file.exists():
        print(f"❌ Error: File not found: {args.card_file}", file=sys.stderr)
        sys.exit(1)

    # Load card from file
    with open(args.card_file) as f:
        card_data = json.load(f)

    # Determine name
    name = args.name or card_data.get("description", args.card_file.stem)

    # Get tags (override or from file)
    if args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    else:
        tags = card_data.get("keywords", [])

    # Connect to Memory API
    api_url = os.getenv("MEMORY_API_URL", "http://localhost:8000")
    client = MemoryClient(base_url=api_url)

    try:
        # Upload memory card
        ref = client.save_memory_card(
            memory_card=card_data,
            name=name,
            tags=tags,
            when_to_use=card_data.get("explanation"),
            author=args.author,
            entity_id=args.entity_id,
            channel=args.channel,
        )

        print("✅ Memory card uploaded successfully!")
        print(f"   Entity ID: {ref.entity_id}")
        print(f"   Version ID: {ref.version_id}")
        print(f"   Channel: {ref.channel}")
        print(f"\n📝 Description: {card_data.get('description', 'N/A')}")
        print(f"🏷️  Tags: {', '.join(tags)}")
        print(f"📂 Category: {card_data.get('category', 'N/A')}")

        # Show evolution statistics if present
        if 'evolution_statistics' in card_data:
            stats = card_data['evolution_statistics']
            print("\n📊 Evolution Statistics:")
            print(f"   Gain: {stats.get('gain', 'N/A')}")
            print(f"   Best Quartile: {stats.get('best_quartile', 'N/A')}")
            print(f"   Survival: {stats.get('survival', 'N/A')}")

        # Show usage statistics if present
        if 'usage' in card_data:
            usage = card_data['usage']
            print("\n📈 Usage Statistics:")
            print(f"   Retrieved: {usage.get('retrieved', 0)} times")
            print(f"   Fitness Impact: {usage.get('increased_fitness', 0.0)}")

    except Exception as e:
        print(f"❌ Error uploading memory card: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
