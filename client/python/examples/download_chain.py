"""
Download a chain from GigaEvo Memory for use in CARL.

Usage:
    python download_chain.py <entity_id> [--channel stable] [--output chain.json]
    python download_chain.py <entity_id> --print  # Print to stdout

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
    parser = argparse.ArgumentParser(description="Download a chain from GigaEvo Memory")
    parser.add_argument("entity_id", help="Entity ID to download")
    parser.add_argument("--channel", default="latest", help="Channel to use (default: latest)")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output file path")
    parser.add_argument("--print", dest="print_output", action="store_true", help="Print to stdout")
    parser.add_argument("--validate", action="store_true", help="Validate chain with CARL")
    parser.add_argument("--info", action="store_true", help="Show chain info only")
    args = parser.parse_args()

    # Connect to Memory API
    api_url = os.getenv("MEMORY_API_URL", "http://localhost:8000")
    client = MemoryClient(base_url=api_url)

    try:
        # Get chain as dict (raw)
        chain_data = client.get_chain_dict(args.entity_id, channel=args.channel)

        # Also get typed chain for validation
        if args.validate or args.info:
            chain = client.get_chain(args.entity_id, channel=args.channel)

        if args.info:
            # Show info only
            metadata = chain_data.get("metadata", {})
            steps = chain_data.get("steps", [])
            print(f"📋 Chain: {metadata.get('name', 'Unknown')}")
            print(f"   Entity ID: {args.entity_id}")
            print(f"   Channel: {args.channel}")
            print(f"   Steps: {len(steps)}")
            print(f"   Max workers: {chain_data.get('max_workers', 1)}")

            if steps:
                print("\n   Step types:")
                from collections import Counter
                types = Counter(s.get("step_type", "llm") for s in steps)
                for t, count in types.items():
                    print(f"     - {t}: {count}")

            if args.validate:
                print("\n✅ Chain validated successfully")
            return

        if args.validate:
            # Chain already loaded above, just confirm
            print(f"✅ Chain validated: {len(chain.steps)} steps", file=sys.stderr)

        # Output
        output_json = json.dumps(chain_data, indent=2, ensure_ascii=False)

        if args.print_output:
            print(output_json)
        elif args.output:
            args.output.write_text(output_json)
            print(f"✅ Chain saved to: {args.output}", file=sys.stderr)
        else:
            # Default: print to stdout
            print(output_json)

    except Exception as e:
        print(f"❌ Error downloading chain: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
