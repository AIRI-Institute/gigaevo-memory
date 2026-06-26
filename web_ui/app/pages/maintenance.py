"""Maintenance page for Gradio web UI."""

import gradio as gr
from typing import Tuple


def maintenance_tab(client):
    """Create the maintenance tab."""

    def clear_all_data(entity_type: str) -> Tuple[str, str]:
        """Clear all data, optionally filtered by entity type."""
        try:
            # Map display names to API entity types
            type_mapping = {
                "All Data": None,
                "Steps": "step",
                "Chains": "chain",
                "Agents": "agent",
                "Memory Cards": "memory_card",
            }

            api_type = type_mapping.get(entity_type)
            result = client.clear_all_data(entity_type=api_type)

            deleted = result.get("deleted", {})
            total = sum(deleted.values())

            details = []
            for etype, count in deleted.items():
                details.append(f"  - {etype.capitalize()}: {count}")

            details_str = "\n".join(details) if details else "  No entities deleted"

            msg = f"✅ Successfully deleted {total} entities:\n{details_str}"
            return "", msg
        except Exception as e:
            return "", f"❌ Error clearing data: {str(e)}"

    def confirm_clear() -> Tuple[str, str]:
        """Show confirmation dialog."""
        return (
            "⚠️ WARNING: This will permanently delete ALL data. This action cannot be undone!\n\n"
            "Click 'Confirm Delete' to proceed or 'Cancel' to abort.",
            ""
        )

    # Build UI
    gr.Markdown("### ⚙️ Maintenance")

    gr.Markdown("""
    **⚠️ DANGER ZONE** — These operations are destructive and cannot be undone.

    Use these options to clear all data from the memory module. Data is soft-deleted
    and may still exist in database backups.
    """)

    with gr.Row():
        with gr.Column():
            entity_type_selector = gr.Radio(
                label="Select data to delete:",
                choices=[
                    "All Data",
                    "Steps",
                    "Chains",
                    "Agents",
                    "Memory Cards",
                ],
                value="All Data",
                interactive=True
            )

        with gr.Column():
            gr.Markdown("")

    # Warning and confirmation area
    warning_box = gr.Markdown(
        "Click the button below to see the confirmation dialog.",
        elem_classes=["status-warning"]
    )

    status = gr.Markdown("")

    # Buttons
    with gr.Row():
        clear_btn = gr.Button("🗑️ Remove All Data", variant="stop", size="lg")
        confirm_btn = gr.Button("⚠️ Confirm Delete", variant="stop", visible=False)
        cancel_btn = gr.Button("Cancel", variant="secondary", visible=False)

    def show_confirm(entity_type):
        """Show confirm/cancel buttons."""
        msg = (
            f"⚠️ **WARNING:** You are about to delete **{entity_type}**.\n\n"
            f"This action **cannot be undone**. All selected data will be soft-deleted.\n\n"
            f"Click **'Confirm Delete'** to proceed or **'Cancel'** to abort."
        )
        return msg, gr.update(visible=True), gr.update(visible=True)

    def hide_confirm():
        """Hide confirm/cancel buttons."""
        return (
            "Click the button below to see the confirmation dialog.",
            gr.update(visible=False),
            gr.update(visible=False)
        )

    def do_clear(entity_type):
        """Execute the clear operation and hide buttons."""
        msg, status = clear_all_data(entity_type)
        return status, gr.update(visible=False), gr.update(visible=False)

    # Event handlers
    clear_btn.click(
        fn=show_confirm,
        inputs=[entity_type_selector],
        outputs=[warning_box, confirm_btn, cancel_btn]
    )

    cancel_btn.click(
        fn=hide_confirm,
        outputs=[warning_box, confirm_btn, cancel_btn]
    )

    confirm_btn.click(
        fn=do_clear,
        inputs=[entity_type_selector],
        outputs=[status, confirm_btn, cancel_btn]
    )

    return status
