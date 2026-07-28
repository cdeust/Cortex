"""Wiki filesystem → DB migration + ghost reconciliation (Phase 1.2 of
redesign, extended for FS<->PG parity).

One-shot idempotent job: walk ~/.claude/methodology/wiki/, parse every
.md file, upsert into wiki.pages, then resolve [[slug]] references
into wiki.links. A fourth pass reconciles wiki.pages against the same
filesystem scan: any row whose rel_path no longer exists on disk (file
deleted, renamed, or purged by wiki_purge — which only ever touches the
FS, never PG) is a "ghost" and is deleted from wiki.pages, cascading via
FK ON DELETE CASCADE to wiki.links and wiki.page_sources (see
pg_schema.py — src_page_id/page_id both CASCADE).

Coverage: PAGE_KINDS-listed directories only (adr/conventions/
explanation/guides/how-to/lessons/notes/reference/rfc/runbook/specs/
tutorial). The `_`-prefixed directories (_kinds/_rules/_views/
_bibliography/_dashboards) and the root README.md are outside
``list_pages``'s scan entirely — they were never upserted, so they can
never appear as ghosts either. No separate exclusion list is needed:
the existence criterion for both phases (upsert, purge) is identical —
"does list_pages() return this rel_path right now".

Re-running is safe — body_hash guards against redundant upsert writes;
the purge phase re-computes ghosts from scratch every run (no state to
go stale).

Invoked as an MCP tool (`wiki_migrate`) or via `python -m
mcp_server.handlers.wiki_migrate [--dry-run]`. Never raises; returns a
summary. dry_run defaults to True (report-only) — matching wiki_purge's
apply=False default — because purging is destructive and this tool is
now exposed over MCP for the first time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp_server.core.wiki_pages import parse_page
from mcp_server.core.wiki_templates import STATUS_VALUES
from mcp_server.handlers._tool_meta import DESTRUCTIVE
from mcp_server.infrastructure.pg_store_wiki import (
    body_hash,
    delete_links_from,
    delete_pages_by_rel_path,
    list_all_rel_paths,
    resolve_unresolved_links,
    upsert_link,
    upsert_page,
)
from mcp_server.infrastructure.wiki_store import list_pages, read_page
from mcp_server.shared.wiki_source_paths import extract_document_paths

# Wiki-link syntax: [[slug]] or [[slug|display text]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# wiki.pages.status's DB CHECK constraint (pg_schema.py) accepts the union
# of: the digital-garden maturity vocabulary ('seedling'/'budding'/
# 'evergreen', the column default) plus 'living' (emitted by
# core/auto_curator.py:475,538 and handlers/consolidation/page_io.py:376)
# plus every kind-specific ADR/specs status in STATUS_VALUES
# (core/wiki_templates.py). Frontmatter is FS-authored and not itself
# constrained, so any value outside this union must be caught here — the
# system boundary (coding-standards.md 3.2) — before it reaches the DB.
_LEGACY_MATURITY_STATUSES = frozenset({"seedling", "budding", "evergreen", "living"})
_VALID_STATUS_VALUES = _LEGACY_MATURITY_STATUSES | {
    v for values in STATUS_VALUES.values() for v in values
}


def _normalize_status(raw_status: str, rel_path: str) -> tuple[str, str | None]:
    """Validate a frontmatter status against wiki.pages' DB CHECK union.

    Precondition: raw_status is a non-empty string (the caller has already
    collapsed missing frontmatter status/maturity to 'seedling').
    Postcondition: returns (raw_status, None) when raw_status is a member
    of _VALID_STATUS_VALUES; otherwise returns ('seedling', <warning>) —
    'seedling' matches the column's own DB default, so an unrecognized
    frontmatter value can never trip pages_status_check.
    """
    if raw_status in _VALID_STATUS_VALUES:
        return raw_status, None
    warning = f"{rel_path}: unknown status '{raw_status}' -> falling back to 'seedling'"
    return "seedling", warning


# ── MCP schema ───────────────────────────────────────────────────────────

schema = {
    "title": "Wiki — migrate FS to PG + reconcile ghosts",
    "annotations": DESTRUCTIVE,
    "description": (
        "One-shot idempotent sync of the filesystem wiki "
        "(~/.claude/methodology/wiki/) into wiki.pages / wiki.links / "
        "wiki.page_sources. Walks every PAGE_KINDS directory, upserts "
        "each page keyed on rel_path (body_hash guards no-op re-writes), "
        "re-resolves [[slug]] links, then reconciles: any wiki.pages row "
        "whose rel_path no longer exists on disk (deleted file, rename, "
        "or a wiki_purge run — which only touches the FS, never PG) is "
        "purged from wiki.pages, cascading via FK ON DELETE CASCADE to "
        "wiki.links and wiki.page_sources. The `_`-prefixed kind dirs "
        "(_kinds/_rules/_views/_bibliography/_dashboards) and the root "
        "README.md are outside the scan entirely on both phases, so they "
        "are never upserted and never purged. Defaults to dry_run=true "
        "(report the ghost rel_paths without deleting); pass "
        "dry_run=false to actually purge. Distinct from `wiki_purge` "
        "(deletes FS files that fail the classifier, never touches PG) — "
        "this tool never touches the FS, only reconciles PG to match it. "
        "A frontmatter status outside wiki.pages' DB CHECK union falls "
        "back to 'seedling' and is reported in warnings (never blocks "
        "the page write). Returns {pages_processed, pages_written, "
        "pages_unchanged, links_written, links_resolved_pass3, "
        "purge: {dry_run, ghost_count, ghost_paths, purged}, errors, "
        "error_count, warnings, warning_count}."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": (
                    "If true (default), report which wiki.pages rows "
                    "would be purged as filesystem ghosts without "
                    "deleting them. Pass false to actually delete."
                ),
            },
        },
    },
}


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


def page_row_from_md(
    rel_path: str, content: str, memory_id: int | None = None
) -> dict[str, Any]:
    """Build an upsert_page payload from a parsed markdown file.

    Public (no leading underscore): reused by ``wiki_write`` (INC6.8,
    I6-D7) to sync a freshly-written page into ``wiki.pages``
    synchronously instead of waiting for the next ``wiki_migrate``
    sweep — a citation row needs a resolvable ``page_id`` immediately
    after the write, not after the next batch migration.
    """
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

    # ADR-0051 STEP 2: extract every legacy documented-file form
    # (documents:/source_file_path:/file:/file:<path> tag) into the
    # canonical list. documents_primary is the 1:1 fast-path scalar.
    documents = extract_document_paths(fm, tags)

    raw_status = fm.get("status") or fm.get("maturity") or "seedling"
    status, status_warning = _normalize_status(raw_status, rel_path)

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
        "status": status,
        # Not a DB column — upsert_page only reads the params it names, so
        # this rides along on the row dict and is popped by
        # _upsert_all_pages before/after the insert to build the run's
        # warnings list (never written to wiki.pages).
        "status_warning": status_warning,
        "lifecycle_state": fm.get("lifecycle_state", "active"),
        "supersedes": fm.get("supersedes"),
        "superseded_by": fm.get("superseded_by"),
        "verified": fm.get("verified"),
        "lead": lead,
        "sections": sections,
        "body": body,
        "body_hash": body_hash(body),
        "documents": documents,
        "documents_primary": documents[0] if documents else None,
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


def find_ghost_rel_paths(fs_rel_paths: list[str], pg_rel_paths: list[str]) -> list[str]:
    """Return the rel_paths present in PG but absent from the current FS scan.

    Pure set difference — no I/O. Precondition: both lists use the same
    rel_path convention (POSIX, relative to the wiki root, as produced by
    ``list_pages``). Postcondition: result is sorted and contains exactly
    the pg_rel_paths not present in fs_rel_paths — a page in fs_rel_paths
    but not yet in PG is not a ghost, it's simply not-yet-migrated.
    """
    fs_set = set(fs_rel_paths)
    return sorted(rp for rp in pg_rel_paths if rp not in fs_set)


def purge_ghost_pages(conn, fs_rel_paths: list[str], *, dry_run: bool = True) -> dict:
    """Reconcile wiki.pages against the filesystem: delete rows with no
    backing file.

    Precondition: fs_rel_paths is the result of the SAME list_pages() scan
    used by the upsert pass in this run — using a stale or differently
    scoped scan would misclassify pages as ghosts.
    Postcondition (dry_run=False): every wiki.pages row whose rel_path is
    not in fs_rel_paths is deleted (cascading to wiki.links/page_sources/
    citations per FK ON DELETE CASCADE); rows whose rel_path IS in
    fs_rel_paths are untouched. (dry_run=True): no row is deleted; the
    same ghost set is still computed and returned for review.

    Deletion goes through the store (delete_pages_by_rel_path) — no SQL
    inline here (Move 5: this handler orchestrates, the store executes).
    """
    pg_rel_paths = list_all_rel_paths(conn)
    ghosts = find_ghost_rel_paths(fs_rel_paths, pg_rel_paths)
    if dry_run or not ghosts:
        return {
            "dry_run": dry_run,
            "ghost_count": len(ghosts),
            "ghost_paths": ghosts,
            "purged": [],
        }
    deleted = delete_pages_by_rel_path(conn, ghosts)
    return {
        "dry_run": dry_run,
        "ghost_count": len(ghosts),
        "ghost_paths": ghosts,
        "purged": sorted(r["rel_path"] for r in deleted),
    }


def _upsert_all_pages(
    root: Path, rel_paths: list[str], conn
) -> tuple[dict[str, int], int, int, list[str], list[str]]:
    """Pass 1 — upsert every page.

    Returns (id_by_rel, written, unchanged, errors, warnings). ``warnings``
    collects non-blocking status-normalization notices (see
    ``_normalize_status``) — an unrecognized frontmatter status never fails
    the page, it falls back to 'seedling' and is reported here instead of
    silently.
    """
    candidate_ids = {
        mid for rp in rel_paths if (mid := _memory_id_from_rel_path(rp)) is not None
    }
    valid_ids = _existing_memory_ids(conn, candidate_ids)

    id_by_rel: dict[str, int] = {}
    written = 0
    unchanged = 0
    errors: list[str] = []
    warnings: list[str] = []
    for rp in rel_paths:
        try:
            content = read_page(root, rp)
            if content is None:
                continue
            mid = _memory_id_from_rel_path(rp)
            mid = mid if mid in valid_ids else None
            row = page_row_from_md(rp, content, memory_id=mid)
            status_warning = row.pop("status_warning", None)
            if status_warning:
                warnings.append(status_warning)
            page_id, was_modified = upsert_page(conn, row)
            id_by_rel[rp] = page_id
            if was_modified:
                written += 1
            else:
                unchanged += 1
        except Exception as e:  # noqa: BLE001 — per-page batch isolation — failure is reported in the returned errors list
            errors.append(f"{rp}: {e}")
    return id_by_rel, written, unchanged, errors, warnings


def _upsert_all_links(
    root: Path, id_by_rel: dict[str, int], conn
) -> tuple[int, list[str]]:
    """Pass 2 — re-scan bodies for [[slug]] refs, upsert into wiki.links."""
    written = 0
    errors: list[str] = []
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
                written += 1
        except Exception as e:  # noqa: BLE001 — per-page batch isolation — failure is reported in the returned errors list
            errors.append(f"{rp} links: {e}")
    return written, errors


def migrate_wiki(wiki_root: Path | str, conn, *, dry_run: bool = True) -> dict:
    """Walk the wiki folder and mirror every .md into wiki.pages + wiki.links,
    then reconcile ghosts.

    Four passes:
      1. Upsert all pages (records each slug → id) — ``_upsert_all_pages``.
      2. Re-scan bodies for [[slug]] refs → upsert into wiki.links —
         ``_upsert_all_links``.
      3. Call resolve_unresolved_links to catch stragglers.
      4. Purge wiki.pages rows whose rel_path no longer exists on disk
         (see purge_ghost_pages). Gated by ``dry_run`` — report-only by
         default.

    Stale memory_ids (from filenames) that no longer exist in the memories
    table are silently dropped — the wiki page survives orphaned.

    Returns a summary dict.
    """
    root = Path(wiki_root)
    rel_paths = list_pages(root)

    id_by_rel, pages_written, pages_unchanged, errors1, warnings = _upsert_all_pages(
        root, rel_paths, conn
    )
    links_written, errors2 = _upsert_all_links(root, id_by_rel, conn)
    resolved = resolve_unresolved_links(conn)

    # Pass 4 — reconcile: purge wiki.pages rows with no backing FS file.
    # Uses the SAME rel_paths scan as Pass 1 so "ghost" is computed against
    # this run's view of the filesystem, not a stale one.
    purge_summary = purge_ghost_pages(conn, rel_paths, dry_run=dry_run)

    # dry_run must be transactionally neutral end-to-end: passes 1-3
    # (upsert_page, delete_links_from/upsert_link, resolve_unresolved_links)
    # write through the same `conn` as pass 4 and have no dry_run gate of
    # their own — only pass 4 checks dry_run internally (see
    # purge_ghost_pages). Committing unconditionally here previously made
    # `--dry-run` persist passes 1-3 despite the name (issue #105). Roll
    # back everything this call wrote when dry_run is requested; commit
    # only on a real (dry_run=False) run.
    if dry_run:
        conn.rollback()
    else:
        conn.commit()

    errors = errors1 + errors2
    return {
        "pages_processed": len(rel_paths),
        "pages_written": pages_written,
        "pages_unchanged": pages_unchanged,
        "links_written": links_written,
        "links_resolved_pass3": resolved,
        "purge": purge_summary,
        "errors": errors[:10],
        "error_count": len(errors),
        "warnings": warnings[:10],
        "warning_count": len(warnings),
    }


async def handler(args: dict | None = None) -> dict:
    """MCP tool entry: run migration + ghost-page reconciliation, return summary."""
    from mcp_server.infrastructure.config import WIKI_ROOT
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import get_shared_store

    args = args or {}
    dry_run = bool(args.get("dry_run", True))
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return migrate_wiki(WIKI_ROOT, store._conn, dry_run=dry_run)


__all__ = [
    "handler",
    "schema",
    "migrate_wiki",
    "find_ghost_rel_paths",
    "purge_ghost_pages",
]


if __name__ == "__main__":
    # Direct CLI invocation: python -m mcp_server.handlers.wiki_migrate [--dry-run]
    import argparse
    import asyncio
    import json as _json

    parser = argparse.ArgumentParser(
        description="Wiki FS -> PG migration + ghost-page reconciliation"
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Report ghost rel_paths without deleting (default).",
    )
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Actually purge ghost rel_paths from wiki.pages.",
    )
    cli_args = parser.parse_args()

    print(
        _json.dumps(
            asyncio.run(handler({"dry_run": cli_args.dry_run})),
            indent=2,
        )
    )
