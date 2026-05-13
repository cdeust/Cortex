"""Handler: wiki_list — enumerate authored wiki pages.

Phase 3.2 of ADR-2244: redirect stubs are filtered from the listing by
default. Pass ``include_redirects: true`` to see them — useful for
migration tooling that needs to audit or clean up old paths.

Phase 5 of ADR-2244: auto-generated pages (frontmatter ``provenance:
auto-generated``, written by ``codebase_analyze``) are also filtered
from the listing by default. At ~8,700 pages they dominate any
listing, but they're lookup tables for code reference rather than
curated content; the default view should be human-authored content.
Pass ``include_auto_generated: true`` to see them.
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
        "journal, files). "
        "Two filters are applied by default and can be opted out of: "
        "(1) redirect stubs (frontmatter ``redirect_to:`` or ``redirect_id:``) "
        "are excluded — pass ``include_redirects: true`` to see them; "
        "(2) auto-generated pages (frontmatter ``provenance: auto-generated``, "
        "produced by ``codebase_analyze``) are excluded — pass "
        "``include_auto_generated: true`` to see them. "
        "Read-only; never modifies anything. Distinct from `wiki_reindex` "
        "which generates the .generated/INDEX.md from the same enumeration, "
        "and from `wiki_read` which fetches one page's content. Latency "
        "<200ms on a 9000-page wiki because each page's frontmatter is read "
        "once for both filter checks. Returns {root, count, pages, "
        "redirect_count, auto_generated_count}."
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
            "include_auto_generated": {
                "type": "boolean",
                "description": (
                    "When true, auto-generated pages (``provenance: "
                    "auto-generated``, typically from ``codebase_analyze``) "
                    "are included. Default false — at ~8,700 pages these "
                    "dominate listings; the default view shows human-"
                    "authored content."
                ),
                "default": False,
            },
        },
    },
}


def _classify_page(rel_path: str) -> tuple[bool, bool]:
    """Read frontmatter once; return (is_redirect_stub, is_auto_generated).

    Both filters share the same disk read and frontmatter parse — important
    because the default ``wiki_list`` walks ~9000 pages.
    """
    try:
        content = read_page(WIKI_ROOT, rel_path)
    except (ValueError, OSError):
        return False, False
    if content is None:
        return False, False
    fm = parse_frontmatter(content)
    redirect_flag = is_redirect(fm)
    raw_prov = fm.get("provenance", "")
    auto_gen_flag = (
        isinstance(raw_prov, str) and raw_prov.strip().lower() == "auto-generated"
    )
    return redirect_flag, auto_gen_flag


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    kind = args.get("kind")
    include_redirects = bool(args.get("include_redirects", False))
    include_auto_generated = bool(args.get("include_auto_generated", False))

    try:
        all_pages = list_pages(WIKI_ROOT, kind=kind if kind else None)
    except (ValueError, OSError) as exc:
        return {"error": f"list failed: {exc}"}

    # Fast path when both filters are disabled — return everything without
    # the per-page frontmatter read.
    if include_redirects and include_auto_generated:
        return {
            "root": str(WIKI_ROOT),
            "count": len(all_pages),
            "pages": all_pages,
            "redirect_count": 0,  # not partitioned in this mode
            "auto_generated_count": 0,
        }

    kept: list[str] = []
    redirect_count = 0
    auto_generated_count = 0
    for rel in all_pages:
        redirect_flag, auto_gen_flag = _classify_page(rel)
        if redirect_flag:
            redirect_count += 1
            if not include_redirects:
                continue
        if auto_gen_flag:
            auto_generated_count += 1
            if not include_auto_generated:
                continue
        kept.append(rel)

    return {
        "root": str(WIKI_ROOT),
        "count": len(kept),
        "pages": kept,
        "redirect_count": redirect_count,
        "auto_generated_count": auto_generated_count,
    }
