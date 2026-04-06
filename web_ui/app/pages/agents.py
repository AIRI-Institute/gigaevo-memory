"""Agents browser/editor page for Gradio web UI with full version management."""

import gradio as gr
from typing import Tuple, List
from .base import (
    parse_json_content,
    extract_entity_fields,
    load_versions_list,
    load_version_detail,
    compute_version_diff,
    revert_entity,
    pin_channel_version,
    promote_channel,
    create_refresh_result,
)


def agents_tab(client):
    """Create the agents tab with list, editor, and version management."""

    # State
    list_data_state = gr.State([])
    selected_entity_id = gr.State(None)
    versions_list_state = gr.State([])

    # ========================================================================
    # Entity List Functions
    # ========================================================================

    def load_agents() -> Tuple[List[List], List, str, str]:
        """Load agents list. Returns (data_for_table, raw_data, status_message, last_update)."""
        try:
            result = client.get_agents(limit=100)
            if not result:
                return create_refresh_result([], [], "✅ No agents found")

            items = result if isinstance(result, list) else result.get("items", [])

            if not items:
                return create_refresh_result([], [], "✅ No agents found")

            table_data = []
            raw_data = []
            for agent in items:
                entity_id = agent.get("entity_id", "")
                meta = agent.get("meta", {})
                name = meta.get("name", "N/A") if isinstance(meta, dict) else "N/A"
                channel = agent.get("channel", "latest")
                tags = ", ".join(meta.get("tags", [])) if isinstance(meta, dict) else ""
                version_id = (
                    agent.get("version_id", "")[:8] if agent.get("version_id") else ""
                )
                table_data.append([entity_id, name, channel, version_id, tags])
                raw_data.append(agent)

            return create_refresh_result(
                table_data, raw_data, f"✅ Loaded {len(table_data)} agents"
            )
        except Exception as e:
            return create_refresh_result([], [], f"❌ Error loading agents: {str(e)}")

    # ========================================================================
    # Entity Load/Save/Delete Functions
    # ========================================================================

    def load_agent(
        entity_id: str, channel: str = "latest"
    ) -> Tuple[str, str, str, str]:
        """Load a specific agent."""
        if not entity_id:
            return "", "", "", "⚠️ No agent ID provided"

        try:
            agent = client.get_agent(entity_id, channel=channel)
            entity_id_resp, name, content = extract_entity_fields(agent)
            return (
                entity_id_resp,
                name,
                content,
                f"✅ Loaded agent: {name} (channel: {channel})",
            )
        except Exception as e:
            return "", "", "", f"❌ Error loading agent: {str(e)}"

    def save_agent(
        entity_id: str,
        name: str,
        content_json: str,
        channel: str = "latest",
        tags: str = "",
        author: str = "",
    ) -> Tuple[str, str, str]:
        """Save agent. Returns (entity_id, status_message, refresh_trigger)."""
        try:
            content, error = parse_json_content(content_json)
            if error:
                return entity_id, f"❌ {error}", ""

            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

            data = {
                "meta": {
                    "name": name or "Untitled",
                    "tags": tag_list,
                    "author": author or None,
                },
                "channel": channel,
                "content": content,
            }

            if entity_id and entity_id.strip():
                data["entity_id"] = entity_id.strip()

            result = client.save_agent(data)
            saved_id = result.get("entity_id", "N/A")
            version_id = (
                result.get("version_id", "")[:8] if result.get("version_id") else ""
            )

            return (
                saved_id,
                f"✅ Saved successfully: {saved_id} (v{version_id})",
                "refresh",
            )
        except Exception as e:
            return entity_id, f"❌ Error saving: {str(e)}", ""

    def delete_agent(entity_id: str) -> Tuple[str, str]:
        """Delete an agent. Returns (status_message, refresh_trigger)."""
        if not entity_id:
            return "⚠️ No agent ID provided", ""

        try:
            client.delete_agent(entity_id)
            return f"✅ Deleted agent: {entity_id}", "refresh"
        except Exception as e:
            return f"❌ Error deleting: {str(e)}", ""

    def clear_editor() -> Tuple[str, str, str, str, str, str, str, str]:
        """Clear the editor."""
        return "", "", "", "", "", "", "✅ Editor cleared", None

    # ========================================================================
    # Version Management Functions
    # ========================================================================

    def load_versions(entity_id: str) -> Tuple[List[List], List, str]:
        """Load versions for an agent."""
        if not entity_id:
            return [], [], "⚠️ Select an agent first"

        table_data, versions, msg = load_versions_list(client, entity_id, "agent", 50)
        return table_data, versions, msg

    def load_version_content(entity_id: str, version_id: str) -> str:
        """Load content of a specific version."""
        if not entity_id or not version_id:
            return "⚠️ Select a version first"

        content, msg = load_version_detail(client, entity_id, version_id, "agent")
        return content

    def show_diff(entity_id: str, from_version: str, to_version: str) -> str:
        """Compute and show diff between two versions."""
        if not entity_id or not from_version or not to_version:
            return "⚠️ Select two versions to compare"

        diff, msg = compute_version_diff(
            client, entity_id, from_version, to_version, "agent"
        )
        return diff

    def revert_to_version(entity_id: str, target_version_id: str) -> Tuple[str, str]:
        """Revert agent to a specific version."""
        if not entity_id or not target_version_id:
            return "⚠️ Select a version to revert to", ""

        new_id, msg = revert_entity(client, entity_id, target_version_id, "agent")
        return new_id, msg

    def pin_version(entity_id: str, channel: str, version_id: str) -> str:
        """Pin a channel to a specific version."""
        if not entity_id or not channel or not version_id:
            return "⚠️ Provide channel and version ID"

        return pin_channel_version(client, entity_id, channel, version_id, "agent")

    def promote_channels(entity_id: str, from_channel: str, to_channel: str) -> str:
        """Promote from one channel to another."""
        if not entity_id or not from_channel or not to_channel:
            return "⚠️ Provide both channels"

        return promote_channel(client, entity_id, from_channel, to_channel, "agent")

    # ========================================================================
    # Row Selection
    # ========================================================================

    def on_select_row(evt: gr.SelectData, list_data: List) -> str:
        """Handle row selection - return entity_id from stored list data."""
        if evt.index is None:
            return None
        row_idx = evt.index[0]
        if row_idx < 0 or row_idx >= len(list_data):
            return None
        return list_data[row_idx].get("entity_id", "")

    def on_select_version_row(evt: gr.SelectData, versions_list: List) -> str:
        """Handle version row selection."""
        if evt.index is None:
            return None
        row_idx = evt.index[0]
        if row_idx < 0 or row_idx >= len(versions_list):
            return None
        return versions_list[row_idx].get("version_id", "")

    # ========================================================================
    # UI Layout
    # ========================================================================

    # Build UI
    with gr.Row():
        # Left: Entity List
        with gr.Column(scale=1):
            gr.Markdown("### 🤖 Agents Library")

            agents_list = gr.Dataframe(
                headers=["ID", "Name", "Channel", "Version", "Tags"],
                datatype=["str", "str", "str", "str", "str"],
                row_count=15,
                column_count=5,
                interactive=False,
                label="Agents",
            )

            with gr.Row():
                refresh_btn = gr.Button("🔄 Refresh", variant="secondary", size="sm")
                status_list = gr.Markdown("")

            last_update_display = gr.Markdown("", elem_classes=["last-update"])
            auto_refresh_timer = gr.Timer(value=20.0)

        # Middle: Editor
        with gr.Column(scale=2):
            gr.Markdown("### ✏️ Agent Editor")

            agent_id_display = gr.Textbox(
                label="Agent ID",
                interactive=False,
                placeholder="Auto-generated for new agents",
            )

            agent_name = gr.Textbox(label="Name", placeholder="Enter agent name...")

            with gr.Row():
                agent_channel = gr.Dropdown(
                    label="Channel", choices=["latest", "stable"], value="latest"
                )
                agent_tags = gr.Textbox(
                    label="Tags (comma separated)", placeholder="tag1, tag2"
                )
                agent_author = gr.Textbox(label="Author", placeholder="Author name")

            agent_content = gr.Code(label="Content (JSON)", language="json", lines=20)

            with gr.Row():
                load_btn = gr.Button("📥 Load Selected", variant="secondary")
                save_btn = gr.Button("💾 Save", variant="primary")
                delete_btn = gr.Button("🗑️ Delete", variant="stop")
                clear_btn = gr.Button("🧹 Clear", variant="secondary")

            status_editor = gr.Markdown("")

        # Right: Version Management
        with gr.Column(scale=1):
            gr.Markdown("### 📚 Version History")

            versions_list = gr.Dataframe(
                headers=["Version", "Version ID", "Created", "Author", "Summary"],
                datatype=["str", "str", "str", "str", "str"],
                row_count=10,
                column_count=5,
                interactive=False,
            )

            with gr.Row():
                versions_btn = gr.Button(
                    "📜 Load Versions", variant="secondary", size="sm"
                )
                status_versions = gr.Markdown("")

            gr.Markdown("### 🔧 Version Actions")

            with gr.Accordion("View Version", open=False):
                selected_version_id = gr.State(None)
                view_version_btn = gr.Button("👁️ View Version Content", size="sm")
                version_content = gr.Code(
                    label="Version Content", language="json", lines=10
                )

            with gr.Accordion("Diff Versions", open=False):
                with gr.Row():
                    diff_from = gr.Textbox(
                        label="From Version", placeholder="Version ID"
                    )
                    diff_to = gr.Textbox(label="To Version", placeholder="Version ID")
                diff_btn = gr.Button("🔍 Compare", size="sm")
                diff_output = gr.Code(label="Diff Result", language="json", lines=10)

            with gr.Accordion("Revert", open=False):
                revert_to = gr.Textbox(
                    label="Target Version ID", placeholder="Version to revert to"
                )
                revert_btn = gr.Button(
                    "↩️ Revert to Version", variant="warning", size="sm"
                )
                revert_status = gr.Markdown("")

            with gr.Accordion("Channel Management", open=False):
                with gr.Row():
                    pin_channel = gr.Dropdown(
                        label="Channel",
                        choices=["stable", "latest", "custom"],
                        value="stable",
                    )
                    pin_version = gr.Textbox(
                        label="Version ID", placeholder="Version ID"
                    )
                pin_btn = gr.Button("📌 Pin Channel", size="sm")

                with gr.Row():
                    promote_from = gr.Dropdown(
                        label="From Channel",
                        choices=["latest", "stable"],
                        value="latest",
                    )
                    promote_to = gr.Dropdown(
                        label="To Channel", choices=["stable", "latest"], value="stable"
                    )
                promote_btn = gr.Button("➡️ Promote", size="sm")

            status_version_actions = gr.Markdown("")

    # ========================================================================
    # Event Handlers
    # ========================================================================

    # List selection
    agents_list.select(
        fn=on_select_row, inputs=[list_data_state], outputs=[selected_entity_id]
    )

    # Load entity
    load_btn.click(
        fn=load_agent,
        inputs=[selected_entity_id, agent_channel],
        outputs=[agent_id_display, agent_name, agent_content, status_editor],
    )

    # Save entity
    refresh_trigger = gr.State("")
    save_btn.click(
        fn=save_agent,
        inputs=[
            agent_id_display,
            agent_name,
            agent_content,
            agent_channel,
            agent_tags,
            agent_author,
        ],
        outputs=[agent_id_display, status_editor, refresh_trigger],
    )

    # Delete entity
    delete_btn.click(
        fn=delete_agent,
        inputs=[agent_id_display],
        outputs=[status_editor, refresh_trigger],
    )

    # Clear editor
    clear_btn.click(
        fn=clear_editor,
        outputs=[
            agent_id_display,
            agent_name,
            agent_tags,
            agent_author,
            agent_content,
            status_editor,
            status_version_actions,
            selected_entity_id,
        ],
    )

    # Refresh list
    def refresh_all(refresh_trig):
        table_data, raw_data, status, last_update = load_agents()
        return table_data, raw_data, status, last_update

    # Watch for save/delete to refresh and auto-refresh timer
    gr.on(
        triggers=[refresh_btn.click, refresh_trigger.change, auto_refresh_timer.tick],
        fn=refresh_all,
        inputs=[refresh_trigger],
        outputs=[agents_list, list_data_state, status_list, last_update_display],
    )

    # ========================================================================
    # Version Management Event Handlers
    # ========================================================================

    # Load versions
    versions_btn.click(
        fn=load_versions,
        inputs=[agent_id_display],
        outputs=[versions_list, versions_list_state, status_versions],
    )

    # Select version
    versions_list.select(
        fn=on_select_version_row,
        inputs=[versions_list_state],
        outputs=[selected_version_id],
    )

    # View version content
    view_version_btn.click(
        fn=load_version_content,
        inputs=[agent_id_display, selected_version_id],
        outputs=[version_content],
    )

    # Diff versions
    diff_btn.click(
        fn=show_diff,
        inputs=[agent_id_display, diff_from, diff_to],
        outputs=[diff_output],
    )

    # Revert
    revert_btn.click(
        fn=revert_to_version,
        inputs=[agent_id_display, revert_to],
        outputs=[agent_id_display, revert_status],
    )

    # Pin channel
    pin_btn.click(
        fn=lambda eid, ch, vid: pin_version(eid, ch, vid),
        inputs=[agent_id_display, pin_channel, pin_version],
        outputs=[status_version_actions],
    )

    # Promote channel
    promote_btn.click(
        fn=lambda eid, fc, tc: promote_channels(eid, fc, tc),
        inputs=[agent_id_display, promote_from, promote_to],
        outputs=[status_version_actions],
    )

    # Initial load trigger
    initial_trigger = gr.Number(value=0, visible=False)

    gr.on(
        triggers=[initial_trigger.change],
        fn=load_agents,
        outputs=[agents_list, list_data_state, status_list, last_update_display],
    )

    return agents_list
