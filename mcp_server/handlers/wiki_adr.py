"""Handler: wiki_adr — create a numbered ADR from structured fields.

Convenience wrapper around wiki_write: finds the next free ADR number,
renders the template via ``core.wiki_pages.build_adr``, and writes the
file. Registers the usual protected PG pointer memory.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import adr_filename, page_path, slugify
from mcp_server.core.wiki_pages import ADR_STATUSES, build_adr
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import (
    WikiExists,
    next_adr_number,
    write_page,
)

schema = {
    "description": (
        "Create a numbered ADR (architecture decision record) from structured "
        "fields. Auto-increments the ADR number."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "context": {"type": "string"},
            "decision": {"type": "string"},
            "consequences": {"type": "string"},
            "status": {
                "type": "string",
                "enum": list(ADR_STATUSES),
                "description": "Defaults to 'accepted'.",
            },
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "context", "decision", "consequences"],
    },
}


async def _store_pointer_memory(rel_path: str, content: str, tags: list[str]) -> None:
    try:
        from mcp_server.handlers import remember

        await remember.handler(
            {
                "content": content[:500],
                "tags": list({"wiki", "adr", *tags}),
                "source": f"wiki://{rel_path}",
                "force": True,
            }
        )
    except Exception:
        return


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    title = str(args.get("title") or "").strip()
    context = str(args.get("context") or "").strip()
    decision = str(args.get("decision") or "").strip()
    consequences = str(args.get("consequences") or "").strip()
    status = str(args.get("status") or "accepted")
    tags = [str(t) for t in (args.get("tags") or [])]

    if not title or not context or not decision or not consequences:
        return {"error": "title, context, decision and consequences are required"}
    if status not in ADR_STATUSES:
        return {"error": f"unknown status: {status}"}

    try:
        number = next_adr_number(WIKI_ROOT)
    except (ValueError, OSError) as exc:
        return {"error": f"cannot determine next ADR number: {exc}"}

    slug = slugify(title)
    filename = adr_filename(number, slug)
    rel_path = str(page_path("adr", filename))

    content = build_adr(
        number=number,
        title=title,
        context=context,
        decision=decision,
        consequences=consequences,
        status=status,
        tags=tags,
    )

    try:
        result = write_page(WIKI_ROOT, rel_path, content, mode="create")
    except WikiExists:
        return {"error": f"ADR already exists: {rel_path}"}
    except (ValueError, OSError) as exc:
        return {"error": f"write failed: {exc}"}

    await _store_pointer_memory(rel_path, content, tags)

    return {
        "path": result.path,
        "number": number,
        "title": title,
        "status": status,
        "created": result.created,
        "bytes_written": result.bytes_written,
        "root": str(WIKI_ROOT),
    }
