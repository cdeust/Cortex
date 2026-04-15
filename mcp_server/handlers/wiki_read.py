"""Handler: wiki_read — fetch the raw markdown of a wiki page."""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import read_page

schema = {
    "description": (
        "Read the raw markdown content of a wiki page by its wiki-relative "
        "path. The path is resolved safely under the wiki root (path traversal "
        "is rejected). Use this to fetch the source of an ADR, decision, or "
        "concept page before quoting, editing, or linking it. Returns the page "
        "content verbatim plus the resolved root for context."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Wiki-relative path of the page to read (no leading slash). "
                    "Path traversal (../) is rejected at the storage layer."
                ),
                "examples": ["adr/0042-pgvector.md", "concepts/wrrf-fusion.md"],
            },
        },
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
