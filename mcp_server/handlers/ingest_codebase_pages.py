"""Wiki-page rendering for ingest_codebase processes."""

from __future__ import annotations

import logging
import re
from typing import Any

from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import write_page

logger = logging.getLogger(__name__)


def _slug(text: str) -> str:
    """Light slugifier for process page filenames."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80]


def render_process_page(process: dict[str, Any]) -> tuple[str, str]:
    """Return (relative_wiki_path, markdown) for a process page."""
    entry = process.get("entry_point") or process.get("name") or "unknown"
    kind = process.get("entry_kind") or "entry"
    depth = process.get("bfs_depth") or process.get("depth") or 0
    symbol_count = process.get("symbol_count") or len(process.get("symbols", []) or [])
    slug = _slug(entry) or "process"
    rel_path = f"reference/codebase/{slug}.md"
    lines = [
        "---",
        f"title: Process — {entry}",
        "kind: reference",
        f"tags: [code-reference, process, {kind}]",
        "---",
        "",
        f"# Process — `{entry}`",
        "",
        f"- **Entry kind:** {kind}",
        f"- **BFS depth:** {depth}",
        f"- **Symbols in flow:** {symbol_count}",
        "",
    ]
    symbols = process.get("symbols") or []
    if symbols:
        lines.append("## Symbols reached")
        for sym in symbols[:50]:
            qn = sym if isinstance(sym, str) else sym.get("qualified_name", "")
            if qn:
                lines.append(f"- `{qn}`")
        if len(symbols) > 50:
            lines.append(f"- … and {len(symbols) - 50} more.")
        lines.append("")
    return rel_path, "\n".join(lines)


def write_process_pages(processes: list[dict[str, Any]]) -> list[str]:
    """Create wiki reference pages for each process. Returns paths written."""
    written: list[str] = []
    for proc in processes:
        try:
            rel_path, markdown = render_process_page(proc)
            write_page(WIKI_ROOT, rel_path, markdown, mode="replace")
            written.append(rel_path)
        except Exception as exc:
            logger.debug("process page write failed: %s", exc)
    return written
