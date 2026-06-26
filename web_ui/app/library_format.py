"""Shared formatters for CARE library metadata in the Gradio UI
(iter #45, §1 P1).

Three helpers — used identically by the Chains and Agents list pages
so future entity types (AgentSkills, MemoryCards) can drop them in
without re-implementing the rendering.

``format_favourite`` returns a star glyph that's easy to spot in a
Dataframe row; ``format_last_run`` returns a compact relative time
("5m ago", "2h ago", "—"); ``pick_display_name`` lets the user-edited
``display_name`` override the URL-safe ``name`` when present, matching
how the CARE TUI labels entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def format_favourite(favourite: Any) -> str:
    """Render the favourite flag.

    Returns ``"⭐"`` when the entity is favourited, empty string
    otherwise. Tolerant of truthy values (1, "true", etc.) so a
    server-side bool change doesn't break the UI.
    """
    return "⭐" if favourite else ""


def pick_display_name(meta: dict | None, library_display_name: Any) -> str:
    """Pick the best human-readable label for an entity.

    Order of precedence (matches CARE TUI behaviour):

      1. ``entity.display_name`` (user-editable label from iter #11).
      2. ``meta["name"]`` (URL-safe name from the version metadata).
      3. ``"N/A"`` placeholder so the cell never renders empty.
    """
    if library_display_name:
        return str(library_display_name)
    if isinstance(meta, dict):
        name = meta.get("name")
        if name:
            return str(name)
    return "N/A"


def format_last_run(last_run_at: Any, *, now: datetime | None = None) -> str:
    """Compact relative timestamp.

    Accepts an ISO string (matches what `_entity_to_dict` produces),
    a ``datetime`` instance, or ``None``. Returns ``"—"`` for missing
    values, "just now" for < 60s, "Xm ago" / "Xh ago" / "Xd ago" for
    larger gaps, and the ISO date for runs older than 30 days
    (a relative "60d ago" carries less info than the absolute date).
    """
    if not last_run_at:
        return "—"

    dt: datetime
    if isinstance(last_run_at, datetime):
        dt = last_run_at
    else:
        try:
            dt = datetime.fromisoformat(str(last_run_at))
        except ValueError:
            return str(last_run_at)

    # Normalise to UTC so naive + aware datetimes can be subtracted.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days < 30:
        return f"{days}d ago"
    return dt.date().isoformat()
