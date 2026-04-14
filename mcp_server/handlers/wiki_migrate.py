"""Wiki filesystem → DB migration (Phase 1.2 of redesign).

One-shot idempotent job: walk ~/.claude/methodology/wiki/, parse every
.md file, upsert into wiki.pages, then resolve [[slug]] references
into wiki.links.

Re-running is safe — body_hash guards against redundant writes.

Invoked as an MCP tool (`wiki_migrate`) or via `python -m
mcp_server.handlers.wiki_migrate`. Never raises; returns a summary.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp_server.core.wiki_pages import parse_page
from mcp_server.infrastructure.pg_store_wiki import (
    body_hash,
    delete_links_from,
    resolve_unresolved_links,
    upsert_link,
    upsert_page,
)
from mcp_server.infrastructure.wiki_store import list_pages, read_page

# Wiki-link syntax: [[slug]] or [[slug|display text]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def _slug_from_rel_path(rel_path: str) -> str:
    """Extract the slug portion from a rel_path like ``adr/cortex/42-foo.md``.

    The slug is the filename stem minus the optional ``<id>-`` prefix.
    """
    stem = Path(rel_path).stem
    m = re.match(r"^\d+-(.+)$", stem)
    return m.group(1) if m else stem


def _extract_body_sections(body: str) -> tuple[str, dict[str, str]]:
    """Split a body into (lead, sections_by_heading).

    Lead = text before the first ``## `` heading.
    Sections = ``## H2`` headings → body text.
    """
    parts = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    lead = parts[0].strip()
    sections: dict[str, str] = {}
    # parts alternates: [lead, heading1, body1, heading2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        heading = parts[i].strip()
        section_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[heading] = section_body
    # Clean lead of any leading H1
    lead = re.sub(r"^#\s+.+?\n", "", lead, count=1).strip()
    return lead, sections


def _page_row_from_md(
    rel_path: str, content: str, memory_id: int | None = None
) -> dict[str, Any]:
    """Build an upsert_page payload from a parsed markdown file."""
    doc = parse_page(content)
    fm = doc.frontmatter or {}
    body = doc.body or ""
    lead, sections = _extract_body_sections(body)
    slug = _slug_from_rel_path(rel_path)

    # Kind is the top-level folder (singular form stored in frontmatter
    # may differ from the directory name — prefer frontmatter if present)
    path_kind = rel_path.split("/", 1)[0] if "/" in rel_path else ""
    kind = fm.get("kind") or path_kind.rstrip("s")

    # Domain is the second path component
    parts = rel_path.split("/")
    domain = fm.get("domain") or (parts[1] if len(parts) >= 3 else "_general")

    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    return {
        "memory_id": memory_id,
        "rel_path": rel_path,
        "slug": slug,
        "kind": kind,
        "title": fm.get("title") or slug,
        "domain": domain,
        "domains": [domain] if domain else [],
        "tags": tags,
        "audience": fm.get("audience", []),
        "requires": fm.get("requires", []),
        "status": fm.get("status") or fm.get("maturity") or "seedling",
        "lifecycle_state": fm.get("lifecycle_state", "active"),
        "supersedes": fm.get("supersedes"),
        "superseded_by": fm.get("superseded_by"),
        "verified": fm.get("verified"),
        "lead": lead,
        "sections": sections,
        "body": body,
        "body_hash": body_hash(body),
    }


def _extract_wikilinks(body: str) -> list[str]:
    """Return the list of [[slug]] targets found in a body."""
    return _WIKILINK_RE.findall(body)


def _memory_id_from_rel_path(rel_path: str) -> int | None:
    """If the filename starts with ``<int>-``, return that int. Else None."""
    stem = Path(rel_path).stem
    m = re.match(r"^(\d+)-", stem)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _existing_memory_ids(conn, ids: set[int]) -> set[int]:
    """Return the subset of ``ids`` that actually exist in the memories table.

    Filenames carry the original memory_id, but those rows may have been
    purged. Avoid FK violations by dropping unknown ids before insert.
    """
    if not ids:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM memories WHERE id = ANY(%s)", (list(ids),))
        rows = cur.fetchall()
    # Connection may have dict_row factory set globally; access defensively.
    out: set[int] = set()
    for r in rows:
        if isinstance(r, dict):
            out.add(r["id"])
        else:
            out.add(r[0])
    return out


def migrate_wiki(wiki_root: Path | str, conn) -> dict:
    """Walk the wiki folder and mirror every .md into wiki.pages + wiki.links.

    Three passes:
      1. Upsert all pages (records each slug → id).
      2. Re-scan bodies for [[slug]] refs → upsert into wiki.links.
      3. Call resolve_unresolved_links to catch stragglers.

    Stale memory_ids (from filenames) that no longer exist in the memories
    table are silently dropped — the wiki page survives orphaned.

    Returns a summary dict.
    """
    root = Path(wiki_root)
    rel_paths = list_pages(root)
    pages_written = 0
    pages_unchanged = 0
    links_written = 0
    errors: list[str] = []

    # Pre-pass — collect candidate memory_ids and filter to those that exist
    candidate_ids = {
        mid for rp in rel_paths if (mid := _memory_id_from_rel_path(rp)) is not None
    }
    valid_ids = _existing_memory_ids(conn, candidate_ids)

    # Pass 1 — upsert every page
    id_by_rel: dict[str, int] = {}
    for rp in rel_paths:
        try:
            content = read_page(root, rp)
            if content is None:
                continue
            mid = _memory_id_from_rel_path(rp)
            mid = mid if mid in valid_ids else None
            row = _page_row_from_md(rp, content, memory_id=mid)
            page_id = upsert_page(conn, row)
            id_by_rel[rp] = page_id
            if page_id >= 0:
                pages_written += 1
            else:
                pages_unchanged += 1
        except Exception as e:
            errors.append(f"{rp}: {e}")

    # Pass 2 — re-scan bodies for wikilinks, upsert into wiki.links
    for rp, page_id in id_by_rel.items():
        try:
            content = read_page(root, rp)
            if content is None:
                continue
            body = parse_page(content).body or ""
            targets = _extract_wikilinks(body)
            if not targets:
                continue
            delete_links_from(conn, page_id)  # idempotent refresh
            for slug in set(targets):
                upsert_link(conn, page_id, slug, link_kind="inline")
                links_written += 1
        except Exception as e:
            errors.append(f"{rp} links: {e}")

    # Pass 3 — resolve any leftover unresolved slugs
    resolved = resolve_unresolved_links(conn)
    conn.commit()

    return {
        "pages_processed": len(rel_paths),
        "pages_written": pages_written,
        "pages_unchanged": pages_unchanged,
        "links_written": links_written,
        "links_resolved_pass3": resolved,
        "errors": errors[:10],
        "error_count": len(errors),
    }


async def handler(args: dict) -> dict:
    """MCP tool entry: run migration, return summary."""
    from mcp_server.infrastructure.config import WIKI_ROOT
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import MemoryStore

    settings = get_memory_settings()
    store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return migrate_wiki(WIKI_ROOT, store._conn)


if __name__ == "__main__":
    # Direct CLI invocation
    import asyncio
    import json as _json

    print(_json.dumps(asyncio.run(handler({})), indent=2))
