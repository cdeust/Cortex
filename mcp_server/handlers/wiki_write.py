"""Handler: wiki_write — author a new wiki page or update an existing one.

Composition root for the authoring path. Renders templated content via
``core.wiki_pages`` when a ``kind`` is supplied, then delegates the
atomic write to ``infrastructure.wiki_store``. After a successful write,
stores a protected PG pointer memory tagged ``wiki`` so ``recall`` can
surface the page like any other memory.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import page_path
from mcp_server.core.wiki_pages import (
    build_adr,
    build_file_doc,
    build_note,
    build_spec,
)
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import (
    WikiExists,
    WikiMissing,
    write_page,
)

schema = {
    "description": (
        "Author a wiki page (adr/specs/files/notes) or append/replace an "
        "existing one. Pages live under ~/.claude/methodology/wiki/ and are "
        "indexed in PostgreSQL as protected pointer memories for recall."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path under the wiki root, e.g. 'notes/my-note.md'.",
            },
            "content": {
                "type": "string",
                "description": "Raw markdown content to write (used when no template fields are given).",
            },
            "mode": {
                "type": "string",
                "enum": ["create", "append", "replace"],
                "description": "Write mode. Defaults to 'create'.",
            },
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "body": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["path"],
    },
}


async def _store_pointer_memory(rel_path: str, content: str, tags: list[str]) -> None:
    """Best-effort: register a protected pointer memory for recall."""
    try:
        from mcp_server.handlers import remember

        await remember.handler(
            {
                "content": content[:500],
                "tags": list({"wiki", *tags}),
                "source": f"wiki://{rel_path}",
                "force": True,
            }
        )
    except Exception:
        return


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    rel_path = str(args.get("path") or "").strip()
    if not rel_path:
        return {"error": "path is required"}
    mode = str(args.get("mode") or "create")
    content = args.get("content")

    if not content:
        return {
            "error": (
                "content is required — render the page yourself "
                "(e.g. via wiki_adr for ADRs) and pass the final markdown."
            )
        }

    try:
        result = write_page(WIKI_ROOT, rel_path, str(content), mode=mode)
    except WikiExists:
        return {"error": f"page already exists: {rel_path}"}
    except WikiMissing:
        return {"error": f"page does not exist: {rel_path}"}
    except (ValueError, OSError) as exc:
        return {"error": f"write failed: {exc}"}

    tags = [str(t) for t in (args.get("tags") or [])]
    await _store_pointer_memory(rel_path, str(content), tags)

    return {
        "path": result.path,
        "mode": result.mode,
        "created": result.created,
        "bytes_written": result.bytes_written,
        "root": str(WIKI_ROOT),
    }


__all__ = [
    "handler",
    "schema",
    "page_path",
    "build_adr",
    "build_spec",
    "build_file_doc",
    "build_note",
]
