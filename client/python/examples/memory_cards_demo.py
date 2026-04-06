#!/usr/bin/env python3
"""
Memory Cards Complete Demo - Demonstrates all CRUD and Search operations.

This script runs through all memory card operations in sequence:
1. Create a new memory card
2. Retrieve the card by ID
3. List all memory cards
4. BM25 search
5. Vector search
6. Hybrid search
7. Batch search with multiple queries

Usage:
    python memory_cards_demo.py

Environment:
    MEMORY_API_URL - API URL (default: http://localhost:8000)
"""

import os
import sys
from pathlib import Path

import httpx

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gigaevo_memory import MemoryClient, SearchType


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print("  " + title)
    print("=" * 70 + "\n")


def print_success(message: str) -> None:
    """Print a success message."""
    print("✅ " + message)


def print_info(message: str) -> None:
    """Print an info message."""
    print("ℹ️  " + message)


def print_error(message: str) -> None:
    """Print an error message."""
    print("❌ " + message)


def handle_optional_vector_search_error(feature_name: str, error: Exception) -> None:
    """Explain why vector-capable searches were skipped, or re-raise unexpected failures."""
    if isinstance(error, ImportError):
        print_info(f"{feature_name} skipped: {error!s}")
        print_info(
            "Install sentence-transformers to enable vector search: pip install sentence-transformers"
        )
        return

    if (
        isinstance(error, httpx.HTTPStatusError)
        and error.response.status_code == 503
        and "Vector search is not enabled" in error.response.text
    ):
        print_info(f"{feature_name} skipped: vector search is disabled on the API server")
        print_info("Set ENABLE_VECTOR_SEARCH=true to enable vector and hybrid search")
        return

    raise error


def main():
    # Connect to Memory API
    api_url = os.getenv("MEMORY_API_URL", "http://localhost:8000")
    client = MemoryClient(base_url=api_url)

    try:
        # ========================================================================
        # 1. CREATE MEMORY CARD
        # ========================================================================
        print_section("1. Creating a New Memory Card")

        memory_card_data = {
            "description": "Batch Processing Pattern for High-Performance Data Pipelines",
            "explanation": "Use this pattern when processing large datasets that can be split into independent chunks. Ideal for ETL workflows, data warehousing, and analytics pipelines where throughput is critical.",
            "keywords": ["pattern", "batch", "performance", "etl", "pipeline", "parallel"],
            "category": "pattern_optimization",
            "task_description": "Optimize data processing pipeline for large-scale operations",
            "evolution_statistics": {
                "gain": 0.82,
                "best_quartile": "Q1",
                "survival": 15
            },
            "usage": {
                "retrieved": 67,
                "increased_fitness": 0.31
            }
        }

        print_info(f"Creating memory card with description: '{memory_card_data['description']}'")

        ref = client.save_memory_card(
            memory_card=memory_card_data,
            name="Batch Processing Pattern",
            tags=memory_card_data["keywords"],
            when_to_use=memory_card_data["explanation"],
            author="demo-script",
            channel="latest",
        )

        print_success("Memory card created successfully!")
        print(f"   Entity ID: {ref.entity_id}")
        print(f"   Version ID: {ref.version_id}")
        print(f"   Channel: {ref.channel}")
        print(f"   Tags: {', '.join(memory_card_data['keywords'])}")

        # Store the entity ID for subsequent operations
        card_id = ref.entity_id

        # ========================================================================
        # 2. GET MEMORY CARD BY ID
        # ========================================================================
        print_section("2. Retrieving Memory Card by ID")

        print_info(f"Fetching card with ID: {card_id}")

        card = client.get_memory_card_dict(card_id, channel="latest")

        print_success("Memory card retrieved successfully!")
        explanation = card.get("explanation", "N/A")
        display_explanation = explanation[:80] + "..." if len(explanation) > 80 else explanation
        print(f"   Description: {card.get('description', 'N/A')}")
        print(f"   Explanation: {display_explanation}")
        print(f"   Category: {card.get('category', 'N/A')}")
        print(f"   Keywords: {', '.join(card.get('keywords', []))}")

        if "evolution_statistics" in card:
            stats = card["evolution_statistics"]
            print("\n   📊 Evolution Statistics:")
            print(f"      Gain: {stats.get('gain', 'N/A')}")
            print(f"      Best Quartile: {stats.get('best_quartile', 'N/A')}")
            print(f"      Survival: {stats.get('survival', 'N/A')}")

        if "usage" in card:
            usage = card["usage"]
            print("\n   📈 Usage Statistics:")
            print(f"      Retrieved: {usage.get('retrieved', 0)} times")
            print(f"      Fitness Impact: {usage.get('increased_fitness', 0.0)}")

        # ========================================================================
        # 3. LIST ALL MEMORY CARDS
        # ========================================================================
        print_section("3. Listing All Memory Cards (Batch Download)")

        print_info("Fetching all memory cards (limit: 10)...")

        listed_cards = client.list_memory_cards(limit=10, offset=0)

        if not listed_cards:
            print_info("No memory cards found in the database")
        else:
            print_success(f"Found {len(listed_cards)} memory cards:\n")

            for i, listed_card in enumerate(listed_cards, 1):
                entity_id = listed_card.entity_id[:8]
                name = listed_card.meta.get('name', 'N/A')
                tags = ', '.join(listed_card.meta.get('tags', []))
                channel = listed_card.channel

                print(f"   {i}. [{entity_id}] {name}")
                print(f"      Channel: {channel}")
                print(f"      Tags: {tags}")
                print()

        # ========================================================================
        # 4. BM25 SEARCH
        # ========================================================================
        print_section("4. BM25 Search (Full-Text Search)")

        query_bm25 = "data processing"
        print_info(f"Searching for: '{query_bm25}' using BM25 full-text search")

        results_bm25 = client.search(
            query=query_bm25,
            search_type=SearchType.BM25,
            top_k=5,
            entity_type="memory_card",
        )

        if not results_bm25:
            print_info("No results found for BM25 search")
        else:
            print_success(f"BM25 search found {len(results_bm25)} results:\n")

            for i, card in enumerate(results_bm25, 1):
                print(f"   {i}. {card.description}")
                print(f"      ID: {card.id}")
                print(f"      Category: {card.category or 'N/A'}")
                print(f"      Keywords: {', '.join(card.keywords or [])}")
                print()

        # ========================================================================
        # 5. VECTOR SEARCH
        # ========================================================================
        print_section("5. Vector Search (Semantic Search)")

        query_vector = "efficient computation performance"
        print_info(f"Searching for: '{query_vector}' using vector similarity search")

        results_vector = []
        vector_summary = "skipped"
        try:
            results_vector = client.search(
                query=query_vector,
                search_type=SearchType.VECTOR,
                top_k=5,
                entity_type="memory_card",
            )

            if not results_vector:
                print_info("No results found for vector search")
                vector_summary = "0 results"
            else:
                print_success(f"Vector search found {len(results_vector)} results:\n")
                vector_summary = f"{len(results_vector)} results"

                for i, card in enumerate(results_vector, 1):
                    print(f"   {i}. {card.description}")
                    print(f"      ID: {card.id}")
                    print(f"      Category: {card.category or 'N/A'}")
                    explanation = card.explanation[:80] + "..." if card.explanation and len(card.explanation) > 80 else (card.explanation or "")
                    if explanation:
                        print(f"      Explanation: {explanation}")
                    print()
        except (ImportError, httpx.HTTPStatusError) as e:
            handle_optional_vector_search_error("Vector search", e)

        # ========================================================================
        # 6. HYBRID SEARCH
        # ========================================================================
        print_section("6. Hybrid Search (BM25 + Vector Combined)")

        query_hybrid = "optimization performance analysis"
        bm25_weight = 0.4
        vector_weight = 0.6

        print_info(f"Searching for: '{query_hybrid}' using hybrid search")
        print_info(f"Weights: BM25={int(bm25_weight * 100)}%, Vector={int(vector_weight * 100)}%")

        results_hybrid = []
        hybrid_summary = "skipped"
        try:
            results_hybrid = client.search(
                query=query_hybrid,
                search_type=SearchType.HYBRID,
                top_k=5,
                entity_type="memory_card",
                hybrid_weights=(bm25_weight, vector_weight),
            )

            if not results_hybrid:
                print_info("No results found for hybrid search")
                hybrid_summary = "0 results"
            else:
                print_success(f"Hybrid search found {len(results_hybrid)} results:\n")
                hybrid_summary = f"{len(results_hybrid)} results"

                for i, card in enumerate(results_hybrid, 1):
                    print(f"   {i}. {card.description}")
                    print(f"      ID: {card.id}")
                    print(f"      Category: {card.category or 'N/A'}")
                    print(f"      Keywords: {', '.join(card.keywords or [])}")
                    print()
        except (ImportError, httpx.HTTPStatusError) as e:
            handle_optional_vector_search_error("Hybrid search", e)

        # ========================================================================
        # 7. BATCH SEARCH (Multiple Queries in Parallel)
        # ========================================================================
        print_section("7. Batch Search (Multiple Queries in Parallel)")

        queries = [
            "data processing pipeline",
            "performance optimization",
            "efficient computation",
        ]

        print_info(f"Running batch search for {len(queries)} queries in parallel:")
        for i, query in enumerate(queries, 1):
            print(f"   {i}. {query}")

        print()

        # BM25 Batch Search
        print_info("Executing BM25 batch search...")

        results_batch_bm25 = client.batch_search(
            queries=queries,
            search_type=SearchType.BM25,
            top_k=3,
        )

        print_success("BM25 batch search completed!\n")

        for query, query_cards in zip(queries, results_batch_bm25):
            print(f"   Query: '{query}'")
            print(f"   Results: {len(query_cards)} cards")
            for card in query_cards[:2]:
                print(f"      - {card.description}")
            print()

        # Hybrid Batch Search
        print("-" * 70)
        print_info("Executing Hybrid batch search (BM25=30%, Vector=70%)...")

        try:
            results_batch_hybrid = client.batch_search(
                queries=queries,
                search_type=SearchType.HYBRID,
                top_k=3,
                hybrid_weights=(0.3, 0.7),
            )

            print_success("Hybrid batch search completed!\n")

            for query, query_cards in zip(queries, results_batch_hybrid):
                print(f"   Query: '{query}'")
                print(f"   Results: {len(query_cards)} cards")
                for card in query_cards[:2]:
                    print(f"      - {card.description}")
                print()
        except (ImportError, httpx.HTTPStatusError) as e:
            handle_optional_vector_search_error("Hybrid batch search", e)

        # ========================================================================
        # SUMMARY
        # ========================================================================
        print_section("Demo Completed Successfully!")

        print("All memory card operations demonstrated:")
        print()
        description_preview = memory_card_data['description'][:50] + "..."
        print(f"   ✅ 1. Created memory card: '{description_preview}'")
        print(f"   ✅ 2. Retrieved card by ID: {card_id[:8]}...")
        print(f"   ✅ 3. Listed all memory cards: {len(listed_cards)} cards found")
        print(f"   ✅ 4. BM25 search: '{query_bm25}' - {len(results_bm25)} results")
        print(f"   ✅ 5. Vector search: '{query_vector}' - {vector_summary}")
        print(f"   ✅ 6. Hybrid search: '{query_hybrid}' - {hybrid_summary}")
        print(f"   ✅ 7. Batch search: {len(queries)} queries processed")
        print()
        print("🎉 All operations completed successfully!")
        print()
        print("💡 Tip: You can now use the individual example scripts in this directory")
        print("   to perform specific operations as needed.")

    except Exception as e:
        print_error(f"Error during demo: {e!s}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        client.close()


if __name__ == "__main__":
    main()
