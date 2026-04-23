"""Handler: wiki_list — enumerate authored wiki pages."""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import PAGE_KINDS
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import list_pages
from mcp_server.handlers._tool_meta import READ_ONLY

schema = {
    "title": "Wiki — list pages",
    "annotations": READ_ONLY,
    "description": (
        "Enumerate every authored wiki page under ~/.claude/methodology/wiki/, "
        "filesystem-walked from the wiki root. Optionally restrict by kind "
        "(adr, specs, guides, reference, conventions, lessons, notes, "
        "journal, files). Use this to browse what already exists before "
        "writing a new page, to feed a downstream selector, or to build a "
        "manual cross-reference. Read-only; never modifies anything. Distinct "
        "from `wiki_reindex` which generates the .generated/INDEX.md from the "
        "same enumeration, and from `wiki_read` which fetches one page's "
        "content. Latency <50ms even for thousands of pages. Returns "
        "{root, count, pages: list[wiki-relative path]}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "kind": {
                "type": "string",
                "description": (
                    "Restrict the listing to a single page kind. Omit to list "
                    "every authored page across all kinds."
                ),
                "enum": list(PAGE_KINDS),
                "examples": ["adr", "lessons", "notes"],
            },
        },
    },
}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    kind = args.get("kind")
    try:
        pages = list_pages(WIKI_ROOT, kind=kind if kind else None)
    except (ValueError, OSError) as exc:
        return {"error": f"list failed: {exc}"}
    return {"root": str(WIKI_ROOT), "count": len(pages), "pages": pages}
