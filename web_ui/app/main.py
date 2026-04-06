"""Gradio web UI for GigaEvo Memory Module."""

import os
import logging

import gradio as gr

from .pages.chains import chains_tab
from .pages.memory_cards import memory_cards_tab
from .pages.search import search_tab
from .pages.showcase import showcase_tab
from .pages.maintenance import maintenance_tab
from .client import MemoryClientWrapper, MemoryClientError
from .themes import AIRI_CSS

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

MEMORY_API_URL = os.getenv("MEMORY_API_URL", "http://localhost:8000")

# Initialize client with error handling
try:
    client = MemoryClientWrapper(MEMORY_API_URL)
    logger.info(f"Connected to Memory API at {MEMORY_API_URL}")
except Exception as e:
    logger.error(f"Failed to initialize Memory client: {e}")
    client = None

# Custom CSS
CUSTOM_CSS = """
.status-success { color: green; font-weight: bold; }
.status-error { color: red; font-weight: bold; }
.status-warning { color: orange; font-weight: bold; }
.last-update { color: #666; font-size: 0.85em; font-style: italic; text-align: center;}
"""

# Create Gradio app (Gradio 6.x compatible - no theme/css in constructor)
with gr.Blocks(title="GigaEvo Memory") as app:
    # Inject CSS for styling (compatible with Gradio versions without `css` kwarg)
    gr.HTML(f"<style>{AIRI_CSS}</style>")
    # Header
    gr.Markdown(
        f"""
        # 🧠 GigaEvo Memory Module

        Persistent memory for CARL artifacts: steps, chains, agents, memory cards.

        **API:** `{MEMORY_API_URL}`
        """
    )

    # Connection status
    if client:
        with gr.Row():
            status_btn = gr.Button(
                "🔍 Check Connection", variant="secondary", size="sm"
            )
            connection_status = gr.Markdown(
                "✅ Connected", elem_classes=["status-success"]
            )

        def check_connection():
            try:
                if client:
                    health = client.health_check()
                    return f"✅ Connected (PostgreSQL: {health.get('postgres', 'N/A')}, Redis: {health.get('redis', 'N/A')})"
                else:
                    return "❌ Client not initialized"
            except MemoryClientError as e:
                return f"❌ Connection failed: {str(e)}"
            except Exception as e:
                return f"❌ Error: {str(e)}"

        status_btn.click(fn=check_connection, outputs=connection_status)

        # Tabs for different entity types
        with gr.Tabs():
            with gr.TabItem("🔗 Chains"):
                chains_tab(client)

            # TODO: return when components will be ready
            # with gr.TabItem("📋 Steps"):
            #     steps_tab(client)
            # with gr.TabItem("🤖 Agents"):
            #     agents_tab(client)

            with gr.TabItem("💡 Memory Cards"):
                memory_cards_tab(client)

            with gr.TabItem("🔍 Search"):
                search_tab(client)

            with gr.TabItem("🎬 Showcase"):
                showcase_tab(client)

            with gr.TabItem("⚙️ Maintenance"):
                maintenance_tab(client)

    else:
        # Error state - client not initialized
        gr.Markdown(
            f"""
            ## ❌ Connection Error

            Failed to initialize Memory client.

            **Troubleshooting:**
            1. Check that the API server is running: `{MEMORY_API_URL}`
            2. Verify the `MEMORY_API_URL` environment variable
            3. Check API logs for errors

            **Run the API:**
            ```bash
            cd api
            uvicorn app.main:app --reload
            ```
            """
        )

    # Footer
    gr.Markdown(
        """
        ---
        **GigaEvo Memory Module** v0.1.0 | [API Docs](/docs) | [OpenAPI](/openapi.yaml)
        """
    )

if __name__ == "__main__":
    logger.info("Starting Gradio web UI...")
    # Gradio 6.x: pass theme and css to launch()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        theme=gr.themes.Soft(),
        css=CUSTOM_CSS,
    )
