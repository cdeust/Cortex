"""Handler: wiki_read — fetch the raw markdown of a wiki page.

Phase 3.2 of ADR-2244: when the page at the requested path is a redirect
stub, follow the chain transparently and return the target's content.
The response carries a ``redirect_chain`` array recording the paths
walked, so callers can detect and surface a "this page moved" hint to
their users when the caller cares.

Caller can opt out of redirect-following via ``follow_redirects: false``
to read the stub itself (useful for admin / migration tooling that
needs to inspect or rewrite the stub).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_redirect import (
    MAX_REDIRECT_DEPTH,
    parse_frontmatter,
    parse_redirect,
    resolve_chain,
)
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import read_page

schema = {
    "title": "Wiki — read page",
    "annotations": READ_ONLY,
    "description": (
        "Fetch the raw markdown source of one wiki page by its wiki-relative "
        "path. Path resolution is sandboxed under the wiki root — absolute "
        "paths and `../` traversal are rejected at the storage layer. When "
        "the page is a redirect stub (frontmatter ``redirect_to:`` or "
        "``redirect_id:``) the chain is followed transparently up to "
        f"{MAX_REDIRECT_DEPTH} hops; cycles and dangling targets surface as "
        "errors. Pass ``follow_redirects: false`` to read the stub itself. "
        "Read-only; never mutates state. Distinct from `wiki_list` which "
        "enumerates available pages, and from `wiki_export` which renders a "
        "page through Pandoc to PDF/DOCX/HTML. Latency <10ms. Returns "
        "{path, content, root, redirect_chain} or {error}."
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
            "follow_redirects": {
                "type": "boolean",
                "description": (
                    "When true (default) redirect stubs are followed "
                    "transparently. When false the stub itself is returned, "
                    "which is useful for admin / migration tooling."
                ),
                "default": True,
            },
        },
    },
}


def _frontmatter_reader(rel_path: str) -> dict[str, object]:
    """Read a page's frontmatter from disk via the sandboxed store.

    Returns an empty dict for missing or unreadable pages — that matches
    the ``parse_redirect`` contract (no redirect = no decoration).
    """
    try:
        content = read_page(WIKI_ROOT, rel_path)
    except (ValueError, OSError):
        return {}
    if content is None:
        return {}
    return parse_frontmatter(content)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    rel_path = str(args.get("path") or "").strip()
    if not rel_path:
        return {"error": "path is required"}
    follow = bool(args.get("follow_redirects", True))

    try:
        content = read_page(WIKI_ROOT, rel_path)
    except (ValueError, OSError) as exc:
        return {"error": f"read failed: {exc}"}
    if content is None:
        return {"error": f"page not found: {rel_path}"}

    # Fast path: caller wants the stub itself, or the page isn't a stub.
    if not follow:
        return {
            "path": rel_path,
            "content": content,
            "root": str(WIKI_ROOT),
            "redirect_chain": [],
        }

    fm = parse_frontmatter(content)
    if parse_redirect(fm) is None:
        return {
            "path": rel_path,
            "content": content,
            "root": str(WIKI_ROOT),
            "redirect_chain": [],
        }

    # Stub — walk the chain to the terminal page.
    resolved = resolve_chain(rel_path, _frontmatter_reader)
    if resolved is None:
        return {
            "error": (
                f"redirect chain from {rel_path} could not be resolved "
                f"(cycle, depth > {MAX_REDIRECT_DEPTH}, or id-only redirect "
                f"without a path)"
            ),
            "path": rel_path,
        }

    try:
        target_content = read_page(WIKI_ROOT, resolved.final_path)
    except (ValueError, OSError) as exc:
        return {"error": f"redirect target read failed: {exc}"}
    if target_content is None:
        return {
            "error": (
                f"redirect chain from {rel_path} terminates at "
                f"{resolved.final_path}, but that page no longer exists"
            ),
            "redirect_chain": list(resolved.chain),
        }

    return {
        "path": resolved.final_path,
        "content": target_content,
        "root": str(WIKI_ROOT),
        "redirect_chain": list(resolved.chain),
    }
