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


def _process_symbol_count(process: dict[str, Any]) -> int:
    """Symbols-in-flow count for a process dict.

    Upstream ``get_processes`` (automatised-pipeline src/main.rs,
    ``do_get_processes``) emits exactly ``{name, entry_point, entry_kind,
    depth, node_count}`` — the count key is ``node_count``. The previous
    reader looked for ``symbol_count``/``symbols`` (keys that never
    existed), so every process read as empty and zero wiki pages were
    ever written (2026-06-11 RCA). ``symbols`` is honoured as a fallback
    because the handler enriches processes with a fetched symbol list.
    """
    raw = process.get("node_count")
    if raw is None:
        return len(process.get("symbols") or [])
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def render_process_page(process: dict[str, Any]) -> tuple[str, str]:
    """Return (relative_wiki_path, markdown) for a process page."""
    entry = process.get("name") or process.get("entry_point") or "unknown"
    kind = process.get("entry_kind") or "entry"
    depth = process.get("depth") or 0
    symbol_count = _process_symbol_count(process)
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
        listed = 0
        for sym in symbols[:50]:
            qn = sym if isinstance(sym, str) else sym.get("qualified_name", "")
            if qn:
                lines.append(f"- `{qn}`")
                listed += 1
        # The handler fetches at most 50 participating symbols; node_count
        # is the authoritative flow size, so the overflow note uses it.
        if symbol_count > listed:
            lines.append(f"- … and {symbol_count - listed} more.")
        lines.append("")
    return rel_path, "\n".join(lines)


def write_process_pages(processes: list[dict[str, Any]]) -> list[str]:
    """Create wiki reference pages for each process. Returns paths written.

    2026-05-17 (user feedback "the wiki is still far from being curated
    documentation"): processes with zero symbols-in-flow produce a
    268-byte stub that carries no information. When the AST graph is
    empty (the common case until ``analyze_codebase`` has been run for
    a project) EVERY process page is empty — 1215 stubs in one audit,
    100% of reference/codebase/. Filter them out: a Process page
    without symbols has nothing to document.
    """
    written: list[str] = []
    skipped_empty = 0
    for proc in processes:
        if _process_symbol_count(proc) == 0:
            skipped_empty += 1
            continue
        try:
            rel_path, markdown = render_process_page(proc)
            write_page(WIKI_ROOT, rel_path, markdown, mode="replace")
            written.append(rel_path)
        except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.debug("process page write failed: %s", exc)
    if skipped_empty:
        logger.info("skipped %d empty process pages (symbol_count=0)", skipped_empty)
    return written
