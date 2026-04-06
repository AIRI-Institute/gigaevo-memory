"""Common utilities for Gradio web UI pages."""

import json
from datetime import datetime
from typing import Tuple, List, Dict, Optional


def format_entity_list(entities: List[Dict]) -> List[List]:
    """Format entity list for Gradio Dataframe.

    Args:
        entities: List of entity dicts

    Returns:
        List of [id, name, channel, tags] rows
    """
    data = []
    for entity in entities:
        entity_id = entity.get("entity_id", "")
        meta = entity.get("meta", {})
        name = meta.get("name", "N/A") if isinstance(meta, dict) else "N/A"
        channel = entity.get("channel", "latest")
        tags = ", ".join(meta.get("tags", [])) if isinstance(meta, dict) else ""
        data.append([entity_id, name, channel, tags])
    return data


def parse_json_content(content_str: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Parse JSON content string.

    Args:
        content_str: JSON string to parse

    Returns:
        (parsed_dict, error_message). On success, error_message is None.
    """
    if not content_str or not content_str.strip():
        return {}, None

    try:
        return json.loads(content_str), None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {str(e)}"


def format_json_content(content: Dict, indent: int = 2) -> str:
    """Format dict as JSON string.

    Args:
        content: Dict to format
        indent: Indentation level

    Returns:
        Formatted JSON string
    """
    return json.dumps(content, indent=indent, ensure_ascii=False)


def handle_api_error(e: Exception, operation: str = "operation") -> str:
    """Format API error for display.

    Args:
        e: Exception that occurred
        operation: Name of operation that failed

    Returns:
        User-friendly error message
    """
    error_type = type(e).__name__
    error_msg = str(e)

    # Check for common errors
    if "Connection" in error_msg or "connect" in error_msg.lower():
        return "❌ Cannot connect to API server. Is it running?"

    if "404" in error_msg or "Not Found" in error_msg:
        return f"❌ {operation.title()} not found"

    if "400" in error_msg or "Bad Request" in error_msg:
        return f"❌ Invalid request: {error_msg}"

    if "401" in error_msg or "Unauthorized" in error_msg:
        return "❌ Unauthorized. Check API credentials."

    if "500" in error_msg or "Internal Server Error" in error_msg:
        return "❌ Server error. Check API logs."

    # Generic error
    return f"❌ {operation.title()} failed: {error_type}: {error_msg}"


def create_entity_data(
    name: str,
    content: Dict,
    entity_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    channel: str = "latest",
) -> Dict:
    """Create entity data structure for API.

    Args:
        name: Entity name
        content: Entity content dict
        entity_id: Optional entity ID (for updates)
        tags: Optional list of tags
        channel: Channel name

    Returns:
        Entity data dict
    """
    data = {
        "meta": {
            "name": name or "Untitled",
            "tags": tags or [],
        },
        "channel": channel,
        "content": content,
    }

    if entity_id and entity_id.strip():
        data["entity_id"] = entity_id.strip()

    return data


def extract_entity_fields(entity: Dict) -> Tuple[str, str, str]:
    """Extract common fields from entity response.

    Args:
        entity: Entity dict from API

    Returns:
        (entity_id, name, content_json)
    """
    entity_id = entity.get("entity_id", "")
    meta = entity.get("meta", {})
    name = meta.get("name", "") if isinstance(meta, dict) else ""
    content = format_json_content(entity.get("content", {}))

    return entity_id, name, content


class EntityTypeConfig:
    """Configuration for different entity types."""

    configs = {
        "steps": {
            "name": "Step",
            "plural": "Steps",
            "icon": "📋",
            "placeholder": '{\n  "type": "llm",\n  "config": {}\n}',
            "type": "step",
        },
        "chains": {
            "name": "Chain",
            "plural": "Chains",
            "icon": "🔗",
            "placeholder": '{\n  "steps": [],\n  "dependencies": {}\n}',
            "type": "chain",
        },
        "agents": {
            "name": "Agent",
            "plural": "Agents",
            "icon": "🤖",
            "placeholder": '{\n  "model": "gpt-4",\n  "tools": []\n}',
            "type": "agent",
        },
        "memory_cards": {
            "name": "Memory Card",
            "plural": "Memory Cards",
            "icon": "💡",
            "placeholder": '{\n  "description": "",\n  "examples": []\n}',
            "type": "memory_card",
        },
    }

    @classmethod
    def get(cls, entity_type: str) -> Dict[str, str]:
        """Get config for entity type."""
        return cls.configs.get(
            entity_type,
            {
                "name": "Entity",
                "plural": "Entities",
                "icon": "📦",
                "placeholder": "{}",
                "type": "entity",
            },
        )


# Version management functions


def load_versions_list(
    client, entity_id: str, entity_type: str = "chain", limit: int = 20
) -> Tuple[List[List], List, str]:
    """Load versions list for an entity.

    Returns:
        (table_data, raw_versions, status_message)
    """
    try:
        versions = client.get_versions(entity_id, entity_type, limit)
        if not versions:
            return [], [], f"✅ No versions found for {entity_id}"

        table_data = []
        for v in versions:
            version_id = v.get("version_id", "")
            version_number = v.get("version_number", 0)
            version_label = f"v{version_number}"

            # Convert datetime to string for Gradio display
            created = v.get("created_at", "")
            if hasattr(created, "isoformat"):
                created = created.isoformat()
            elif created:
                created = str(created)

            author = v.get("author", "N/A") or "N/A"
            summary = v.get("change_summary", "") or ""
            table_data.append([version_label, version_id, created, author, summary])

        return table_data, versions, f"✅ Loaded {len(versions)} versions"
    except Exception as e:
        return [], [], f"❌ Error loading versions: {str(e)}"


def load_version_detail(
    client, entity_id: str, version_id: str, entity_type: str = "chain"
) -> Tuple[str, str]:
    """Load a specific version's content.

    Returns:
        (content_json, status_message)
    """
    try:
        version = client.get_version(entity_id, version_id, entity_type)
        content = format_json_content(version.get("content", {}))
        meta = version.get("meta", {})
        name = meta.get("name", "N/A") if isinstance(meta, dict) else "N/A"
        version_number = version.get("version_number", 0)
        return content, f"✅ Loaded version v{version_number} ({name})"
    except Exception as e:
        return "", f"❌ Error loading version: {str(e)}"


def compute_version_diff(
    client,
    entity_id: str,
    from_version: str,
    to_version: str,
    entity_type: str = "chain",
) -> Tuple[str, str]:
    """Compute diff between two versions.

    Returns:
        (diff_json, status_message)
    """
    try:
        diff = client.diff_versions(entity_id, from_version, to_version, entity_type)
        diff_json = format_json_content(diff)
        return diff_json, f"✅ Diff: {from_version} → {to_version}"
    except Exception as e:
        return "", f"❌ Error computing diff: {str(e)}"


def revert_entity(
    client, entity_id: str, target_version_id: str, entity_type: str = "chain"
) -> Tuple[str, str]:
    """Revert entity to a specific version.

    Returns:
        (new_version_id, status_message)
    """
    try:
        result = client.revert(entity_id, target_version_id, entity_type)
        new_id = result.get("version_id", "")
        new_number = result.get("version_number", 0)
        return (
            new_id,
            f"✅ Reverted to version {target_version_id[:8]}, created new version v{new_number}",
        )
    except Exception as e:
        return "", f"❌ Error reverting: {str(e)}"


def pin_channel_version(
    client, entity_id: str, channel: str, version_id: str, entity_type: str = "chain"
) -> str:
    """Pin a channel to a specific version."""
    try:
        client.pin_channel(entity_id, channel, version_id, entity_type)
        return f"✅ Pinned channel '{channel}' to version {version_id}"
    except Exception as e:
        return f"❌ Error pinning: {str(e)}"


def promote_channel(
    client,
    entity_id: str,
    from_channel: str,
    to_channel: str,
    entity_type: str = "chain",
) -> str:
    """Promote a channel from one to another."""
    try:
        client.promote(entity_id, from_channel, to_channel, entity_type)
        return f"✅ Promoted '{from_channel}' → '{to_channel}'"
    except Exception as e:
        return f"❌ Error promoting: {str(e)}"


# Search functions


def load_facets(client) -> Tuple[Dict, str]:
    """Load search facets for filters.

    Returns:
        (facets_dict, status_message)
    """
    try:
        facets = client.get_facets()
        return facets, "✅ Loaded search facets"
    except Exception as e:
        return {}, f"❌ Error loading facets: {str(e)}"


def unified_search_entities(
    client,
    query: str,
    search_type: str = "bm25",
    entity_type: str = "memory_card",
    tags: List[str] = None,
    namespace: str = None,
    channel: str = "latest",
    top_k: int = 20,
    hybrid_weights: tuple = (0.5, 0.5),
) -> Tuple[List[List], str]:
    """Perform unified search with BM25, vector, or hybrid search types.

    Args:
        client: Memory client wrapper
        query: Search query text
        search_type: Type of search ('bm25', 'vector', or 'hybrid')
        entity_type: Type of entity to search
        tags: Optional tags filter
        namespace: Optional namespace filter
        channel: Version channel
        top_k: Number of results to return
        hybrid_weights: Tuple of (bm25_weight, vector_weight) for hybrid search

    Returns:
        (table_data, status_message)
    """
    try:
        result = client.unified_search(
            query=query,
            search_type=search_type,
            top_k=top_k,
            entity_type=entity_type,
            tags=tags,
            namespace=namespace,
            channel=channel,
            hybrid_weights=hybrid_weights,
        )

        hits = result.get("hits", [])

        if not hits:
            return [], f"✅ No results found for '{query}' using {search_type} search"

        data = []
        for hit in hits:
            entity_id = hit.get("entity_id", "")
            entity_type_display = hit.get("entity_type", "N/A")
            name = hit.get("name", "N/A")
            score = f"{hit.get('score', 0):.4f}"
            channel_disp = hit.get("channel", "latest")
            tags_str = ", ".join(hit.get("tags", []))
            data.append(
                [entity_id, entity_type_display, name, score, channel_disp, tags_str]
            )

        return data, f"✅ Found {len(hits)} results using {search_type} search"
    except Exception as e:
        return [], f"❌ Unified search error: {str(e)}"


def batch_unified_search(
    client,
    queries: List[str],
    search_type: str = "bm25",
    entity_type: str = "memory_card",
    tags: List[str] = None,
    namespace: str = None,
    channel: str = "latest",
    top_k: int = 20,
    hybrid_weights: tuple = (0.5, 0.5),
) -> Tuple[List[List[List]], str]:
    """Perform batch unified search.

    Args:
        client: Memory client wrapper
        queries: List of search query texts
        search_type: Type of search ('bm25', 'vector', or 'hybrid')
        entity_type: Type of entity to search
        tags: Optional tags filter
        namespace: Optional namespace filter
        channel: Version channel
        top_k: Number of results per query
        hybrid_weights: Tuple of (bm25_weight, vector_weight) for hybrid search

    Returns:
        (all_table_data, status_message) where all_table_data is a list of
        table data lists, one per query
    """
    try:
        result = client.batch_search(
            queries=queries,
            search_type=search_type,
            top_k=top_k,
            entity_type=entity_type,
            tags=tags,
            namespace=namespace,
            channel=channel,
            hybrid_weights=hybrid_weights,
        )

        all_results = result.get("results", [])
        total_queries = result.get("total_queries", len(queries))

        if not all_results:
            return (
                [],
                f"✅ No results found for {total_queries} queries using {search_type} search",
            )

        all_table_data = []
        for hits in all_results:
            table_data = []
            for hit in hits:
                entity_id = hit.get("entity_id", "")
                entity_type_display = hit.get("entity_type", "N/A")
                name = hit.get("name", "N/A")
                score = f"{hit.get('score', 0):.4f}"
                channel_disp = hit.get("channel", "latest")
                tags_str = ", ".join(hit.get("tags", []))
                table_data.append(
                    [
                        entity_id,
                        entity_type_display,
                        name,
                        score,
                        channel_disp,
                        tags_str,
                    ]
                )
            all_table_data.append(table_data)

        total_hits = sum(len(results) for results in all_results)
        return (
            all_table_data,
            f"✅ Found {total_hits} total results for {total_queries} queries using {search_type} search",
        )
    except Exception as e:
        return [], f"❌ Batch search error: {str(e)}"


# Auto-refresh utilities


def format_last_update() -> str:
    """Format current timestamp for "Last updated" display.

    Returns:
        Formatted string like "Last updated: 14:32:45"
    """
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    return f"*Last updated: {time_str}*"


def create_refresh_result(
    table_data: List[List], raw_data: List, status_message: str
) -> Tuple[List[List], List, str, str]:
    """Create a complete refresh result with timestamp.

    Args:
        table_data: The formatted table data for display
        raw_data: The raw entity data for internal use
        status_message: The status message to display

    Returns:
        (table_data, raw_data, status_message, last_update_display)
    """
    last_update = format_last_update()
    return table_data, raw_data, status_message, last_update
