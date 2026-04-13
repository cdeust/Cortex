"""Wiki API handlers for the visualization HTTP server.

Exposes wiki pages via /api/wiki/list and /api/wiki/page endpoints.
Pages are stored on the filesystem; this module reads them via wiki_store.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.core.wiki_pages import parse_page
from mcp_server.infrastructure.wiki_store import list_pages, read_page


def list_wiki_pages(wiki_root: Path) -> list[dict]:
    """List all wiki pages with parsed frontmatter metadata."""
    pages = list_pages(wiki_root)
    result = []
    for rel_path in pages:
        content = read_page(wiki_root, rel_path)
        if content is None:
            continue
        doc = parse_page(content)
        fm = doc.frontmatter
        stem = Path(rel_path).stem
        result.append({
            "path": rel_path,
            "title": fm.get("title", stem),
            "kind": fm.get("kind", ""),
            "domain": fm.get("domain", ""),
            "maturity": fm.get("maturity", ""),
            "tags": fm.get("tags", []),
            "created": str(fm.get("created", "")),
            "updated": str(fm.get("updated", "")),
        })
    return result


def read_wiki_page(wiki_root: Path, rel_path: str) -> dict:
    """Read a single wiki page with metadata and body."""
    if "/../" in rel_path or rel_path.startswith("../") or "\x00" in rel_path:
        return {"error": "invalid path"}
    content = read_page(wiki_root, rel_path)
    if content is None:
        return {"error": "not found", "path": rel_path}
    doc = parse_page(content)
    return {
        "path": rel_path,
        "meta": doc.frontmatter,
        "body": doc.body,
    }
