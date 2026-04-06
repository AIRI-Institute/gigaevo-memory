"""Unified search page for Gradio web UI with BM25, vector, and hybrid search."""

import gradio as gr
import json
from typing import Tuple, List
from .base import (
    load_facets,
    unified_search_entities,
    batch_unified_search,
)


def search_tab(client):
    """Create the unified search tab with BM25, vector, and hybrid search."""

    # State for selected entity
    selected_row_data = gr.State(None)

    # ========================================================================
    # Entity Loading Functions
    # ========================================================================

    def load_entity(entity_id: str, entity_type: str) -> Tuple[str, str]:
        """Load entity details."""
        if not entity_id:
            return "", "⚠️ No entity ID provided"

        try:
            # Get entity based on type
            if entity_type == "step":
                entity = client.get_step(entity_id)
            elif entity_type == "chain":
                entity = client.get_chain(entity_id)
            elif entity_type == "agent":
                entity = client.get_agent(entity_id)
            elif entity_type == "memory_card":
                entity = client.get_memory_card(entity_id)
            else:
                return "", f"⚠️ Unknown entity type: {entity_type}"

            # Format entity
            content = json.dumps(entity, indent=2, ensure_ascii=False)
            name = entity.get("meta", {}).get("name", "N/A")
            return content, f"✅ Loaded {entity_type}: {name}"
        except Exception as e:
            return "", f"❌ Error loading entity: {str(e)}"

    # ========================================================================
    # Unified Search Functions
    # ========================================================================

    def perform_unified_search(
        query: str,
        search_type: str,
        entity_type: str,
        tags: str,
        namespace: str,
        channel: str,
        top_k: int,
        bm25_weight: float,
        vector_weight: float,
    ) -> Tuple[List[List], str]:
        """Perform unified search with BM25, vector, or hybrid."""
        if not query or not query.strip():
            return [], "⚠️ Enter a search query"

        try:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

            # Normalize weights
            total_weight = bm25_weight + vector_weight
            if total_weight > 0:
                bm25_weight = bm25_weight / total_weight
                vector_weight = vector_weight / total_weight
            hybrid_weights = (bm25_weight, vector_weight)

            data, msg = unified_search_entities(
                client=client,
                query=query.strip(),
                search_type=search_type,
                entity_type=entity_type if entity_type != "all" else "memory_card",
                tags=tag_list,
                namespace=namespace if namespace else None,
                channel=channel,
                top_k=top_k,
                hybrid_weights=hybrid_weights,
            )

            return data, msg
        except Exception as e:
            return [], f"❌ Unified search error: {str(e)}"

    def perform_batch_unified_search(
        queries_str: str,
        search_type: str,
        entity_type: str,
        tags: str,
        namespace: str,
        channel: str,
        top_k: int,
        bm25_weight: float,
        vector_weight: float,
    ) -> Tuple[str, str]:
        """Perform batch unified search."""
        if not queries_str or not queries_str.strip():
            return "", "⚠️ Enter search queries (one per line)"

        try:
            queries = [q.strip() for q in queries_str.strip().split("\n") if q.strip()]
            if not queries:
                return "", "⚠️ No valid queries found"

            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

            # Normalize weights
            total_weight = bm25_weight + vector_weight
            if total_weight > 0:
                bm25_weight = bm25_weight / total_weight
                vector_weight = vector_weight / total_weight
            hybrid_weights = (bm25_weight, vector_weight)

            all_data, msg = batch_unified_search(
                client=client,
                queries=queries,
                search_type=search_type,
                entity_type=entity_type if entity_type != "all" else "memory_card",
                tags=tag_list,
                namespace=namespace if namespace else None,
                channel=channel,
                top_k=top_k,
                hybrid_weights=hybrid_weights,
            )

            # Format results for display
            output_lines = []
            for i, (query, table_data) in enumerate(zip(queries, all_data)):
                output_lines.append(f"## Query {i + 1}: {query}")
                output_lines.append(f"Found {len(table_data)} results")
                for row in table_data:
                    output_lines.append(
                        f"  - [{row[0][:8]}] {row[2]} (score: {row[3]})"
                    )
                output_lines.append("")

            return "\n".join(output_lines), msg
        except Exception as e:
            return "", f"❌ Batch search error: {str(e)}"

    # ========================================================================
    # Facets Functions
    # ========================================================================

    def load_and_display_facets() -> Tuple[str, str, str, str]:
        """Load facets and format for display."""
        try:
            facets, msg = load_facets(client)

            # Format facets for dropdown/checkbox display
            entity_types = list(facets.get("entity_types", {}).keys())
            tags = list(facets.get("tags", {}).keys())
            authors = list(facets.get("authors", {}).keys())
            namespaces = list(facets.get("namespaces", {}).keys())

            return (
                ",".join(entity_types) if entity_types else "",
                ",".join(tags) if tags else "",
                ",".join(authors) if authors else "",
                ",".join(namespaces) if namespaces else "",
            )
        except Exception as e:
            return "", "", "", f"❌ Error loading facets: {str(e)}"

    # ========================================================================
    # Row Selection Helper
    # ========================================================================

    def capture_selection(evt: gr.SelectData):
        return evt.index

    def load_selected_entity(row_data):
        if row_data and len(row_data) >= 2:
            entity_id = row_data[0]
            entity_type = row_data[1]
            details, msg = load_entity(entity_id, entity_type)
            return details, msg
        return "", "⚠️ Select a result first"

    # ========================================================================
    # UI Layout
    # ========================================================================

    gr.Markdown("### 🔍 Unified Search")

    gr.Markdown("""
    **Search across all entities using three powerful search methods:**

    - **BM25**: Full-text search using PostgreSQL's built-in text search. Best for keyword matching.
    - **Vector**: Semantic search using embeddings. Best for finding similar content by meaning.
    - **Hybrid**: Combines both methods with adjustable weights. Best for comprehensive results.
    """)

    with gr.Row():
        with gr.Column(scale=3):
            unified_query = gr.Textbox(
                label="Search Query", placeholder="Enter your search query...", lines=2
            )

        with gr.Column(scale=1):
            unified_search_type = gr.Radio(
                label="Search Type",
                choices=["bm25", "vector", "hybrid"],
                value="bm25",
                info="BM25: text | Vector: semantic | Hybrid: combined",
            )

    with gr.Row():
        with gr.Column(scale=1):
            unified_entity_type = gr.Dropdown(
                label="Entity Type",
                choices=["all", "step", "chain", "agent", "memory_card"],
                value="all",
            )
        with gr.Column(scale=1):
            unified_tags = gr.Textbox(
                label="Tags (comma separated)", placeholder="tag1, tag2"
            )
        with gr.Column(scale=1):
            unified_namespace = gr.Textbox(label="Namespace", placeholder="Namespace")

    with gr.Row():
        with gr.Column(scale=1):
            unified_channel = gr.Dropdown(
                label="Channel", choices=["", "latest", "stable"], value="latest"
            )
        with gr.Column(scale=1):
            unified_top_k = gr.Slider(
                label="Top K", minimum=5, maximum=100, value=20, step=5
            )
        with gr.Column(scale=1):
            gr.HTML("")  # Spacer

    with gr.Accordion("🎚️ Hybrid Weights (for Hybrid Search)", open=False):
        gr.Markdown("**Adjust the weight balance between BM25 and Vector search:**")
        with gr.Row():
            bm25_weight = gr.Slider(
                label="BM25 Weight",
                minimum=0.0,
                maximum=1.0,
                value=0.5,
                step=0.1,
                info="Full-text search importance",
            )
            vector_weight = gr.Slider(
                label="Vector Weight",
                minimum=0.0,
                maximum=1.0,
                value=0.5,
                step=0.1,
                info="Semantic search importance",
            )

    with gr.Row():
        unified_search_btn = gr.Button("🚀 Search", variant="primary", scale=1)

    unified_status = gr.Markdown("")

    unified_results = gr.Dataframe(
        headers=["ID", "Type", "Name", "Score", "Channel", "Tags"],
        datatype=["str", "str", "str", "str", "str", "str"],
        row_count=15,
        column_count=6,
        interactive=False,
        label="Search Results",
    )

    # Entity details
    gr.Markdown("### 📄 Entity Details")

    unified_entity_details = gr.Code(
        label="Entity JSON", language="json", lines=15, interactive=False
    )

    unified_load_btn = gr.Button("📥 Load Selected", variant="secondary")

    # Event handlers for unified search
    unified_search_btn.click(
        fn=perform_unified_search,
        inputs=[
            unified_query,
            unified_search_type,
            unified_entity_type,
            unified_tags,
            unified_namespace,
            unified_channel,
            unified_top_k,
            bm25_weight,
            vector_weight,
        ],
        outputs=[unified_results, unified_status],
    )

    unified_results.select(fn=capture_selection, outputs=[selected_row_data])

    unified_load_btn.click(
        fn=lambda rd: load_selected_entity(rd)
        if rd
        else ("", "⚠️ Select a result first"),
        inputs=[selected_row_data],
        outputs=[unified_entity_details, unified_status],
    )

    # Batch search section
    gr.Markdown("---")
    gr.Markdown("### 📦 Batch Search")

    with gr.Accordion("Search Multiple Queries at Once", open=False):
        gr.Markdown(
            "Enter multiple queries (one per line) to search them all in parallel."
        )

        unified_batch_queries = gr.Textbox(
            label="Queries (one per line)",
            placeholder="Query 1\nQuery 2\nQuery 3",
            lines=5,
        )

        unified_batch_search_btn = gr.Button("🚀 Batch Search", variant="secondary")
        unified_batch_status = gr.Markdown("")
        unified_batch_results = gr.Textbox(
            label="Batch Results", lines=20, interactive=False
        )

        unified_batch_search_btn.click(
            fn=perform_batch_unified_search,
            inputs=[
                unified_batch_queries,
                unified_search_type,
                unified_entity_type,
                unified_tags,
                unified_namespace,
                unified_channel,
                unified_top_k,
                bm25_weight,
                vector_weight,
            ],
            outputs=[unified_batch_results, unified_batch_status],
        )

    # Facets section
    gr.Markdown("---")
    gr.Markdown("### 📊 Available Facets")

    with gr.Accordion("Load Search Facets", open=False):
        facets_btn = gr.Button("🔄 Load Facets", variant="secondary", size="sm")
        _ = gr.Markdown("")  # Status placeholder for future use

        with gr.Row():
            facets_entity_types = gr.Textbox(
                label="Available Entity Types", interactive=False
            )
            facets_tags = gr.Textbox(label="Available Tags", interactive=False)
        with gr.Row():
            facets_authors = gr.Textbox(label="Available Authors", interactive=False)
            facets_namespaces = gr.Textbox(
                label="Available Namespaces", interactive=False
            )

        facets_btn.click(
            fn=load_and_display_facets,
            outputs=[
                facets_entity_types,
                facets_tags,
                facets_authors,
                facets_namespaces,
            ],
        )

    return unified_results
