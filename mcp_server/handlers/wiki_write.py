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
        "Author a new wiki page (adr/specs/files/notes/lessons/...) or append/"
        "replace content on an existing one. Pages live under "
        "~/.claude/methodology/wiki/ and are indexed in PostgreSQL as protected "
        "pointer memories so recall can surface them like any other memory. "
        "When path looks like an ADR or note kind and structured fields are "
        "given (title/summary/body), the content is rendered from the matching "
        "template; otherwise raw 'content' is written verbatim. Use this for "
        "any document that should outlive the session."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Wiki-relative path of the page (no leading slash). The "
                    "first path segment determines the page kind."
                ),
                "examples": ["notes/recall-regression.md", "lessons/dont-mock-db.md"],
            },
            "content": {
                "type": "string",
                "description": (
                    "Raw markdown content. Used when structured fields "
                    "(title/summary/body) are not provided. Markdown is preserved verbatim."
                ),
            },
            "mode": {
                "type": "string",
                "description": (
                    "Write mode. 'create' refuses if the page exists; "
                    "'append' adds to the bottom; 'replace' overwrites."
                ),
                "enum": ["create", "append", "replace"],
                "default": "create",
                "examples": ["create", "append"],
            },
            "title": {
                "type": "string",
                "description": "Page title (used when rendering from template).",
                "examples": ["Recall regression triaged 2026-04-12"],
            },
            "summary": {
                "type": "string",
                "description": "One-paragraph summary placed near the top of the rendered page.",
                "examples": ["FlashRank ONNX cache divergence; clearing fixed it."],
            },
            "body": {
                "type": "string",
                "description": "Main markdown body inserted into the template.",
            },
            "tags": {
                "type": "array",
                "description": "Free-form tags attached to both the wiki frontmatter and the pointer memory.",
                "items": {"type": "string"},
                "default": [],
                "examples": [["lesson", "recall"], ["adr", "embeddings"]],
            },
        },
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
