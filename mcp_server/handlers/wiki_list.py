"""Handler: wiki_list — enumerate authored wiki pages.

Phase 3.2 of ADR-2244: redirect stubs are filtered from the listing by
default. Pass ``include_redirects: true`` to see them — useful for
migration tooling that needs to audit or clean up old paths.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.wiki_layout import PAGE_KINDS
from mcp_server.core.wiki_redirect import is_redirect, parse_frontmatter
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_store import list_pages, read_page

schema = {
    "title": "Wiki — list pages",
    "annotations": READ_ONLY,
    "description": (
        "Enumerate every authored wiki page under ~/.claude/methodology/wiki/, "
        "filesystem-walked from the wiki root. Optionally restrict by kind "
        "(adr, specs, guides, reference, conventions, lessons, notes, "
        "journal, files). Redirect stubs (frontmatter ``redirect_to:`` or "
        "``redirect_id:``) are excluded by default; pass "
        "``include_redirects: true`` to see them. Read-only; never modifies "
        "anything. Distinct from `wiki_reindex` which generates the "
        ".generated/INDEX.md from the same enumeration, and from `wiki_read` "
        "which fetches one page's content. Latency <50ms even for thousands "
        "of pages. Returns {root, count, pages, redirect_count}."
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
            "include_redirects": {
                "type": "boolean",
                "description": (
                    "When true, redirect stubs are included in the listing. "
                    "Default false — most callers want the live pages only."
                ),
                "default": False,
            },
        },
    },
}


def _is_redirect_page(rel_path: str) -> bool:
    """True iff the page at ``rel_path`` declares a redirect in its frontmatter.

    Reads the file via the sandboxed store and parses only the
    frontmatter block — cheap on a 9000-page wiki because the
    frontmatter is at the top of the file and we don't need to load
    the body.
    """
    try:
        content = read_page(WIKI_ROOT, rel_path)
    except (ValueError, OSError):
        return False
    if content is None:
        return False
    return is_redirect(parse_frontmatter(content))


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    kind = args.get("kind")
    include_redirects = bool(args.get("include_redirects", False))

    try:
        all_pages = list_pages(WIKI_ROOT, kind=kind if kind else None)
    except (ValueError, OSError) as exc:
        return {"error": f"list failed: {exc}"}

    if include_redirects:
        return {
            "root": str(WIKI_ROOT),
            "count": len(all_pages),
            "pages": all_pages,
            "redirect_count": 0,  # not partitioned in this mode
        }

    live_pages: list[str] = []
    redirect_count = 0
    for rel in all_pages:
        if _is_redirect_page(rel):
            redirect_count += 1
        else:
            live_pages.append(rel)
    return {
        "root": str(WIKI_ROOT),
        "count": len(live_pages),
        "pages": live_pages,
        "redirect_count": redirect_count,
    }
