"""
Run a chain from GigaEvo Memory using CARL executor.

Usage:
    python run_chain.py <entity_id> --input "Your input text here"
    python run_chain.py <entity_id> --input-file input.txt --output-file result.json
    python run_chain.py <entity_id> --channel stable --input "Analyze this"

Environment:
    MEMORY_API_URL - API URL (default: http://localhost:8000)
    OPENAI_API_KEY - OpenAI API key (default: sk-test)
    OPENAI_BASE_URL - OpenAI-compatible API base URL (optional)
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gigaevo_memory import MemoryClient


async def run_chain(
    entity_id: str,
    channel: str,
    input_text: str,
    output_file: Path | None = None,
    validate: bool = False,
    verbose: bool = False,
):
    """Load and execute a chain from memory."""
    from mmar_carl import DAGExecutor, ReasoningContext, create_openai_client

    # Connect to Memory API
    api_url = os.getenv("MEMORY_API_URL", "http://localhost:8000")
    client = MemoryClient(base_url=api_url)

    # Create LLM client for execution
    api_key = os.getenv("OPENAI_API_KEY", "sk-test")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    llm_client = create_openai_client(
        api_key=api_key,
        model=model,
        base_url=base_url,
    )

    try:
        # Load chain from memory
        if verbose:
            print(f"📥 Loading chain {entity_id} from channel '{channel}'...", file=sys.stderr)

        chain = client.get_chain(entity_id, channel=channel)

        if verbose:
            print(f"✅ Chain loaded: {len(chain.steps)} steps", file=sys.stderr)

        # Validate if requested
        if validate:
            if verbose:
                print("🔍 Validating chain...", file=sys.stderr)
            # Validation happens during get_chain()

        # Create execution context
        context = ReasoningContext(
            outer_context=input_text,
            api=llm_client,
            endpoint_key="default",
        )

        # Create executor
        executor = DAGExecutor(
            max_workers=chain.max_workers,
            enable_progress=chain.enable_progress,
        )

        if verbose:
            print("🚀 Executing chain...", file=sys.stderr)
            print(f"   Max workers: {chain.max_workers}", file=sys.stderr)
            print(f"   Steps: {[s.title for s in chain.steps]}", file=sys.stderr)

        # Execute chain
        result = await executor.execute(chain.steps, context)

        # Get final output (last successful step result)
        final_output = None
        for step_result in reversed(result.step_results):
            if step_result.success:
                final_output = step_result.result
                break

        # Format output
        output = {
            "chain_id": entity_id,
            "channel": channel,
            "input": input_text,
            "result": final_output,
            "success": result.success,
            "total_execution_time": result.total_execution_time,
            "token_usage": result.token_usage,
            "step_results": {},
        }

        # Add step results
        for step_result in result.step_results:
            output["step_results"][str(step_result.step_number)] = {
                "title": step_result.step_title,
                "step_type": str(step_result.step_type),
                "result": step_result.result,
                "success": step_result.success,
                "error": step_result.error_message,
                "execution_time": step_result.execution_time,
            }

        # Output result
        output_json = json.dumps(output, indent=2, ensure_ascii=False, default=str)

        if output_file:
            output_file.write_text(output_json)
            print(f"✅ Result saved to: {output_file}", file=sys.stderr)
        else:
            print(output_json)

        return output

    except Exception as e:
        import traceback
        error_output = {
            "chain_id": entity_id,
            "channel": channel,
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }

        if output_file:
            output_file.write_text(json.dumps(error_output, indent=2))
            print(f"❌ Error: {e}", file=sys.stderr)
        else:
            print(json.dumps(error_output, indent=2))

        sys.exit(1)

    finally:
        client.close()
        await llm_client.close()


def main():
    parser = argparse.ArgumentParser(description="Run a chain from GigaEvo Memory")
    parser.add_argument("entity_id", help="Chain entity ID")
    parser.add_argument("--channel", default="latest", help="Channel to use (default: latest)")
    parser.add_argument("--input", "-i", default=None, help="Input text for the chain")
    parser.add_argument("--input-file", type=Path, default=None, help="Read input from file")
    parser.add_argument("--output-file", "-o", type=Path, default=None, help="Write result to file")
    parser.add_argument("--validate", action="store_true", help="Validate chain before execution")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Get input text
    if args.input:
        input_text = args.input
    elif args.input_file:
        if not args.input_file.exists():
            print(f"Error: Input file not found: {args.input_file}", file=sys.stderr)
            sys.exit(1)
        input_text = args.input_file.read_text()
    else:
        # Use default input if no input provided and stdin is a TTY
        if sys.stdin.isatty():
            input_text = "Analyze the following text: GigaEvo Memory is a persistent storage system for CARL artifacts including steps, chains, agents, and memory cards. It provides versioning, search, and evolutionary capabilities."
        else:
            input_text = sys.stdin.read()

    # Run chain
    asyncio.run(run_chain(
        entity_id=args.entity_id,
        channel=args.channel,
        input_text=input_text,
        output_file=args.output_file,
        validate=args.validate,
        verbose=args.verbose,
    ))


if __name__ == "__main__":
    main()
