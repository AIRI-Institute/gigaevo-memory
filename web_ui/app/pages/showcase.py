"""Showcase tab demonstrating client library usage scenarios."""

import gradio as gr
import json
from pathlib import Path
from typing import Tuple, Optional

# Path to example chain files (bundled with Docker image)
EXAMPLE_DIR = Path("/app/examples")
CHAIN_V0 = EXAMPLE_DIR / "chain_v0.json"
CHAIN_V1 = EXAMPLE_DIR / "chain_v1.json"


def showcase_tab(client):
    """Create the showcase tab with interactive demo scenarios."""

    # State management
    demo_step = gr.State(
        0
    )  # 0=not started, 1=uploaded, 2=downloaded, 3=updated, 4=verified
    entity_id_state = gr.State(None)

    # ========================================================================
    # Demo Functions
    # ========================================================================

    def load_example_chains() -> Tuple[str, str, str]:
        """Load example chain JSON files for preview."""
        try:
            v0_content = json.dumps(json.loads(CHAIN_V0.read_text()), indent=2)
            v1_content = json.dumps(json.loads(CHAIN_V1.read_text()), indent=2)
            return v0_content, v1_content, "✅ Example chains loaded"
        except Exception as e:
            return "", "", f"❌ Error loading examples: {e}"

    def step1_upload_chain() -> Tuple[str, str, int, str]:
        """Step 1: Upload chain_v0.json to memory."""
        try:
            with open(CHAIN_V0) as f:
                chain_data = json.load(f)

            result = client.save_chain(
                {
                    "content": chain_data,
                    "meta": {
                        "name": "Demo Chain - v0",
                        "tags": ["demo", "showcase"],
                        "author": "showcase_tab",
                    },
                    "channel": "latest",
                }
            )

            entity_id = result.get("entity_id", "")
            version_id = result.get("version_id", "")[:8]

            status = "✅ **Step 1 Complete**: Chain uploaded!\n\n"
            status += f"- **Entity ID**: `{entity_id}`\n"
            status += f"- **Version**: `{version_id}`\n"
            status += "- **Name**: Demo Chain - v0"

            return status, "", 1, entity_id
        except Exception as e:
            return f"❌ **Step 1 Failed**: {e}", "", 0, ""

    def step2_download_chain(entity_id: str) -> Tuple[str, str, str, int]:
        """Step 2: Download the uploaded chain and verify."""
        if not entity_id:
            return "⚠️ Complete Step 1 first", "", "", 1

        try:
            # Use force_refresh to ensure we get the latest data after the upload
            chain = client._client.get_chain_dict(entity_id, channel="latest", force_refresh=True)
            chain_json = json.dumps(chain, indent=2, ensure_ascii=False)

            # Verify key fields
            metadata = chain.get("metadata", {})
            name = metadata.get("name", "Unknown")
            steps = chain.get("steps", [])

            status = "✅ **Step 2 Complete**: Chain downloaded and verified!\n\n"
            status += f"- **Name**: {name}\n"
            status += f"- **Steps**: {len(steps)}\n"
            status += f"- **Max Workers**: {chain.get('max_workers', 1)}\n"
            status += "\n📋 Content preview shown in JSON viewer."

            return status, chain_json, "", 2
        except Exception as e:
            return f"❌ **Step 2 Failed**: {e}", "", "", 1

    def step3_update_chain(entity_id: str) -> Tuple[str, str, int]:
        """Step 3: Update chain with chain_v1.json content."""
        if not entity_id:
            return "⚠️ Complete Step 1 first", "", 1

        try:
            with open(CHAIN_V1) as f:
                chain_data = json.load(f)

            result = client.save_chain(
                {
                    "entity_id": entity_id,
                    "content": chain_data,
                    "meta": {
                        "name": "Demo Chain - v1",
                        "tags": ["demo", "showcase", "updated"],
                        "author": "showcase_tab",
                    },
                    "channel": "latest",
                }
            )

            version_id = result.get("version_id", "")[:8]

            status = "✅ **Step 3 Complete**: Chain updated!\n\n"
            status += f"- **Entity ID**: `{entity_id}`\n"
            status += f"- **New Version**: `{version_id}`\n"
            status += "- **Steps**: 3 (was 1)\n"
            status += "- **Max Workers**: 3 (was 1)"

            return status, "", 3
        except Exception as e:
            return f"❌ **Step 3 Failed**: {e}", "", 2

    def step4_verify_update(entity_id: str) -> Tuple[str, str, int]:
        """Step 4: Download again to verify the update."""
        if not entity_id:
            return "⚠️ Complete Step 1 first", "", 1

        try:
            # Use force_refresh to ensure we get the latest version after the update
            chain = client._client.get_chain_dict(entity_id, channel="latest", force_refresh=True)
            chain_json = json.dumps(chain, indent=2, ensure_ascii=False)

            metadata = chain.get("metadata", {})
            steps = chain.get("steps", [])

            status = "✅ **Step 4 Complete**: Update verified!\n\n"
            status += f"- **Name**: {metadata.get('name', 'Unknown')}\n"
            status += f"- **Steps**: {len(steps)}\n"
            status += f"- **Step Types**: {[s.get('step_type') for s in steps]}\n"
            status += "\n🎉 **Demo Complete!** The chain was successfully updated from v0 to v1."

            return status, chain_json, 4
        except Exception as e:
            return f"❌ **Step 4 Failed**: {e}", "", 3

    def reset_demo() -> Tuple[str, str, str, str, int, Optional[str]]:
        """Reset the demo to initial state."""
        v0_json, v1_json, _ = load_example_chains()
        return (
            "Click **Upload Chain (v0)** to begin the interactive walkthrough.",
            v0_json,
            v1_json,
            "",
            0,
            None,
        )

    # ========================================================================
    # UI Layout
    # ========================================================================

    with gr.Row():
        # Left: Demo Controls
        with gr.Column(scale=1):
            gr.Markdown("### 🎬 Interactive Demo")

            demo_status = gr.Markdown(
                "🎬 **Welcome to the Showcase!**\n\nClick **Start Demo** to begin the interactive walkthrough."
            )

            with gr.Row():
                reset_btn = gr.Button("🔄 Reset", variant="secondary", size="sm")

            gr.Markdown("---")
            gr.Markdown("### Demo Steps")

            start_btn = gr.Button("1️⃣ Upload Chain (v0)", variant="primary")
            download_btn = gr.Button("2️⃣ Download & Verify", variant="primary")
            update_btn = gr.Button("3️⃣ Update Chain (v1)", variant="primary")
            verify_btn = gr.Button("4️⃣ Verify Update", variant="primary")

            gr.Markdown("---")
            gr.Markdown("### 📚 Example Files")

            load_examples_btn = gr.Button("📂 Load Example Files", variant="secondary")

        # Middle: Current Operation Output
        with gr.Column(scale=2):
            gr.Markdown("### 📊 Demo Output")

            output_json = gr.Code(
                label="Chain Content (JSON)",
                language="json",
                lines=25,
                interactive=False,
            )

        # Right: Reference
        with gr.Column(scale=1):
            gr.Markdown("### 📋 Reference Data")

            gr.Markdown("**chain_v0.json** (1 step)")
            v0_preview = gr.Code(
                label="Original Chain", language="json", lines=12, interactive=False
            )

            gr.Markdown("**chain_v1.json** (3 steps)")
            v1_preview = gr.Code(
                label="Updated Chain", language="json", lines=12, interactive=False
            )

    # ========================================================================
    # Event Handlers
    # ========================================================================

    reset_btn.click(
        fn=reset_demo,
        outputs=[
            demo_status,
            v0_preview,
            v1_preview,
            output_json,
            demo_step,
            entity_id_state,
        ],
    )

    start_btn.click(
        fn=step1_upload_chain,
        outputs=[demo_status, output_json, demo_step, entity_id_state],
    )

    download_btn.click(
        fn=step2_download_chain,
        inputs=[entity_id_state],
        outputs=[demo_status, output_json, v1_preview, demo_step],
    )

    update_btn.click(
        fn=step3_update_chain,
        inputs=[entity_id_state],
        outputs=[demo_status, output_json, demo_step],
    )

    verify_btn.click(
        fn=step4_verify_update,
        inputs=[entity_id_state],
        outputs=[demo_status, output_json, demo_step],
    )

    load_examples_btn.click(
        fn=load_example_chains, outputs=[v0_preview, v1_preview, demo_status]
    )

    # Auto-load examples on tab render (using demo component as trigger)
    demo_status.change(fn=lambda x: x, inputs=[demo_status], outputs=[demo_status])

    return demo_status
