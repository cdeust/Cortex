"""Handler: wiki_read — fetch the raw markdown of a wiki page."""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import read_page
from mcp_server.handlers._tool_meta import READ_ONLY

schema = {
    "title": "Wiki — read page",
    "annotations": READ_ONLY,
    "description": (
        "Fetch the raw markdown source of one wiki page by its wiki-relative "
        "path. Path resolution is sandboxed under the wiki root — absolute "
        "paths and `../` traversal are rejected at the storage layer. Read-"
        "only; never mutates state. Use this to quote, link, or edit-prep an "
        "ADR/spec/lesson page before further action. Distinct from `wiki_list` "
        "which enumerates available pages, and from `wiki_export` which "
        "renders a page through Pandoc to PDF/DOCX/HTML. Latency <10ms. "
        "Returns {path, content (markdown verbatim), root} or {error}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Wiki-relative path of the page to read (no leading "
                    "slash, no `..`). Must end in .md and resolve under the "
                    "wiki root."
                ),
                "examples": [
                    "adr/0042-pgvector.md",
                    "concepts/wrrf-fusion.md",
                    "specs/cortex/recall-pipeline.md",
                ],
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
