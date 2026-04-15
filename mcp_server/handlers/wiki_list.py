"""Handler: wiki_list — enumerate authored wiki pages."""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import PAGE_KINDS
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import list_pages

schema = {
    "description": (
        "List every authored wiki page under ~/.claude/methodology/wiki/, "
        "optionally restricted to a single kind (adr, specs, guides, "
        "reference, conventions, lessons, notes, journal, files). Use this to "
        "browse what already exists before writing a new page or to feed a "
        "downstream selector. Returns the wiki root, page count, and a list "
        "of wiki-relative paths."
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
