"""Handler: wiki_list — enumerate authored wiki pages."""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import PAGE_KINDS
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import list_pages

schema = {
    "description": "List authored wiki pages. Optionally filter by kind (adr/specs/files/notes).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(PAGE_KINDS),
                "description": "Restrict to a single page kind.",
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
