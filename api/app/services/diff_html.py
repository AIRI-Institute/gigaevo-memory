"""HTML renderer for the browser-friendly diff endpoint (TODO §8 P3).

The JSON-format response carries the raw RFC-6902 patch operations. CARE's
TUI consumes that. Browser users opening the URL want a readable page;
this module renders a small self-contained HTML document — inline CSS,
no external assets — so it works in any context (file://, dashboard
iframe, plain curl-to-file).

Kept as a pure function over the diff data so it's straightforward to
unit-test without spinning up the FastAPI app.
"""

from __future__ import annotations

import html
import json
from typing import Any, Iterable

#: RFC-6902 patch operations. Used to colour-code rows in the rendered page.
_KNOWN_OPS = ("add", "remove", "replace", "move", "copy", "test")

# Compact, dependency-free CSS. Lives next to the renderer so the markup
# and styles stay in lockstep.
_CSS = """
:root {
  --bg: #fafafa; --fg: #1a1a1a; --muted: #6b6b6b;
  --border: #e0e0e0; --code-bg: #f4f4f4;
  --add: #2ea043; --add-bg: #e6f4ea;
  --remove: #d1242f; --remove-bg: #fbeaea;
  --replace: #9a6700; --replace-bg: #fff5d6;
  --move: #5a32a3; --move-bg: #f0e8fa;
  --copy: #0969da; --copy-bg: #e2efff;
  --test: #6b6b6b; --test-bg: #ececec;
}
* { box-sizing: border-box; }
body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       color: var(--fg); background: var(--bg); margin: 0; padding: 24px; }
h1 { margin: 0 0 4px; font-size: 18px; }
header { border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 20px; }
header dl { display: grid; grid-template-columns: 140px 1fr; gap: 4px 12px; margin: 8px 0 0;
            font-size: 13px; }
header dt { color: var(--muted); }
header dd { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.stats { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; font-size: 12px; }
.stats .chip { padding: 2px 8px; border-radius: 10px; font-weight: 600; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 8px 12px; vertical-align: top; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
td.op { font-weight: 600; white-space: nowrap; width: 90px; }
td.path { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #444;
          word-break: break-all; max-width: 360px; }
td.value pre { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
               background: var(--code-bg); padding: 6px 8px; border-radius: 4px;
               white-space: pre-wrap; word-break: break-word; max-height: 240px; overflow: auto; }
.row.add    td.op { color: var(--add); }      .row.add    { background: var(--add-bg); }
.row.remove td.op { color: var(--remove); }   .row.remove { background: var(--remove-bg); }
.row.replace td.op { color: var(--replace); } .row.replace { background: var(--replace-bg); }
.row.move    td.op { color: var(--move); }    .row.move    { background: var(--move-bg); }
.row.copy    td.op { color: var(--copy); }    .row.copy    { background: var(--copy-bg); }
.row.test    td.op { color: var(--test); }    .row.test    { background: var(--test-bg); }
.empty { text-align: center; padding: 40px 0; color: var(--muted); font-style: italic; }
.chip.add    { background: var(--add-bg); color: var(--add); }
.chip.remove { background: var(--remove-bg); color: var(--remove); }
.chip.replace{ background: var(--replace-bg); color: var(--replace); }
.chip.move   { background: var(--move-bg); color: var(--move); }
.chip.copy   { background: var(--copy-bg); color: var(--copy); }
.chip.test   { background: var(--test-bg); color: var(--test); }
""".strip()


def _normalise_patch(patch: Any) -> list[dict[str, Any]]:
    """Coerce the patch payload into a list of op dicts.

    Accepts the two shapes ``svc.diff_versions`` may yield:
      * A list of op dicts already.
      * A JSON-encoded string (``jsonpatch.make_patch(...).to_string()``).
    """
    if isinstance(patch, str):
        try:
            decoded = json.loads(patch) if patch.strip() else []
        except json.JSONDecodeError:
            return []
        patch = decoded
    if not isinstance(patch, list):
        return []
    return [op for op in patch if isinstance(op, dict)]


def _format_value(value: Any) -> str:
    """Pretty-print a JSON-ish value, escaped for HTML.

    Plain scalars surface as-is; structures get a 2-space indented JSON
    dump. ``None`` (an actual JSON null) becomes the literal ``null``.
    """
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    else:
        rendered = json.dumps(value, ensure_ascii=False)
    return html.escape(rendered)


def _summarise(ops: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {kind: 0 for kind in _KNOWN_OPS}
    for op in ops:
        kind = op.get("op", "")
        if kind in counts:
            counts[kind] += 1
    return counts


def _render_row(op: dict[str, Any]) -> str:
    kind = str(op.get("op", "")).lower()
    css_class = kind if kind in _KNOWN_OPS else "test"
    path = html.escape(str(op.get("path", "")))

    # Build the "value" cell from whichever fields the op carries. Only
    # `value` (for add/replace/test) and `from` (for move/copy) are
    # standardised; we show every non-op/path key for forward compat.
    extras: list[str] = []
    for key in ("value", "from"):
        if key in op:
            extras.append(
                f'<div><strong>{html.escape(key)}:</strong>'
                f'<pre>{_format_value(op[key])}</pre></div>'
            )
    if not extras:
        extras.append('<div class="empty" style="text-align:left">—</div>')

    return (
        f'<tr class="row {css_class}">'
        f'<td class="op">{html.escape(kind) or "—"}</td>'
        f'<td class="path">{path}</td>'
        f'<td class="value">{"".join(extras)}</td>'
        f"</tr>"
    )


def render_diff_html(
    *,
    entity_type: str,
    entity_id: str,
    from_version: str,
    to_version: str,
    patch: Any,
) -> str:
    """Render a complete HTML document for the diff.

    Self-contained — no external CSS / JS. Safe to serve directly via
    ``HTMLResponse`` from FastAPI.
    """
    ops = _normalise_patch(patch)
    counts = _summarise(ops)

    chips = " ".join(
        f'<span class="chip {kind}">{counts[kind]} {kind}</span>'
        for kind in _KNOWN_OPS
        if counts[kind] > 0
    )
    if not chips:
        chips = '<span class="chip test">no changes</span>'

    rows = "\n".join(_render_row(op) for op in ops) or (
        '<tr><td colspan="3" class="empty">'
        "No operations — the two versions are identical.</td></tr>"
    )

    title = (
        f"Diff: {html.escape(entity_type)} "
        f"{html.escape(entity_id)} ({html.escape(from_version[:8])} → "
        f"{html.escape(to_version[:8])})"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <dl>
    <dt>Entity type</dt><dd>{html.escape(entity_type)}</dd>
    <dt>Entity ID</dt><dd>{html.escape(entity_id)}</dd>
    <dt>From version</dt><dd>{html.escape(from_version)}</dd>
    <dt>To version</dt><dd>{html.escape(to_version)}</dd>
  </dl>
  <div class="stats">{chips}</div>
</header>
<table>
<thead><tr><th>Op</th><th>Path</th><th>Value</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""
