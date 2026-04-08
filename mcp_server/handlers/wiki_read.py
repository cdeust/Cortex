"""Handler: wiki_read — fetch the raw markdown of a wiki page."""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import read_page

schema = {
    "description": "Read the raw markdown of a wiki page by its relative path.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path under the wiki root.",
            },
        },
        "required": ["path"],
    },
}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    rel_path = str(args.get("path") or "").strip()
    if not rel_path:
        return {"error": "path is required"}
    try:
        content = read_page(WIKI_ROOT, rel_path)
    except (ValueError, OSError) as exc:
        return {"error": f"read failed: {exc}"}
    if content is None:
        return {"error": f"page not found: {rel_path}"}
    return {"path": rel_path, "content": content, "root": str(WIKI_ROOT)}
