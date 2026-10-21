"""The database half of ``wiki_migrate``: one store operation.

``handlers/wiki_migrate.py`` reads and parses every page first (filesystem
and pure work, no connection held), then calls ``apply_wiki_mirror`` once.
The four passes run on that one connection and end with a rollback on a dry
run or a commit otherwise, exactly as they did when the handler held the
store's connection itself (ADR-0463, issue #105); only the file reads moved
out (ADR-1112 increment 2).

source: ADR-0463 (the passes), ADR-1112 (as one operation)
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_wiki import (
    delete_links_from,
    delete_pages_by_rel_path,
    list_all_rel_paths,
    resolve_unresolved_links,
    upsert_link,
    upsert_page,
)
from mcp_server.infrastructure.store_operations import store_operation
from mcp_server.infrastructure.wiki_handler_queries import existing_memory_ids


def find_ghost_rel_paths(fs_rel_paths: list[str], pg_rel_paths: list[str]) -> list[str]:
    """rel_paths present in PG but absent from the filesystem scan, sorted.

    A page on disk and not yet in PG is not a ghost, it is not migrated yet."""
    fs_set = set(fs_rel_paths)
    return sorted(rp for rp in pg_rel_paths if rp not in fs_set)


def purge_ghost_pages(
    conn: Any, fs_rel_paths: list[str], *, dry_run: bool = True
) -> dict:
    """Delete wiki.pages rows with no backing file (cascades to links,
    page_sources and citations); a dry run reports the same set and deletes
    nothing. ``fs_rel_paths`` must come from the same scan as the upsert."""
    ghosts = find_ghost_rel_paths(fs_rel_paths, list_all_rel_paths(conn))
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "ghost_count": len(ghosts),
        "ghost_paths": ghosts,
        "purged": [],
    }
    if not dry_run and ghosts:
        deleted = delete_pages_by_rel_path(conn, ghosts)
        summary["purged"] = sorted(r["rel_path"] for r in deleted)
    return summary


def _upsert_pages(
    conn: Any, pages: list[dict]
) -> tuple[dict[str, int], int, int, list]:
    candidates = [p["memory_id"] for p in pages if p["memory_id"] is not None]
    valid = set(existing_memory_ids(conn, candidates))
    id_by_rel: dict[str, int] = {}
    written = unchanged = 0
    errors: list[str] = []
    for page in pages:
        rel_path = page["rel_path"]
        try:
            row = dict(page["row"])
            row["memory_id"] = page["memory_id"] if page["memory_id"] in valid else None
            page_id, was_modified = upsert_page(conn, row)
            id_by_rel[rel_path] = page_id
            written += int(bool(was_modified))
            unchanged += int(not was_modified)
        except Exception as exc:  # noqa: BLE001 — per-page batch isolation — failure is reported in the returned errors list
            errors.append(f"{rel_path}: {exc}")
    return id_by_rel, written, unchanged, errors


def _upsert_links(
    conn: Any, id_by_rel: dict[str, int], links: dict[str, list[str]]
) -> tuple[int, list[str]]:
    written = 0
    errors: list[str] = []
    for rel_path, page_id in id_by_rel.items():
        targets = links.get(rel_path) or []
        if not targets:
            continue
        try:
            delete_links_from(conn, page_id)  # idempotent refresh
            for slug in targets:
                upsert_link(conn, page_id, slug, link_kind="inline")
                written += 1
        except Exception as exc:  # noqa: BLE001 — per-page batch isolation — failure is reported in the returned errors list
            errors.append(f"{rel_path} links: {exc}")
    return written, errors


@store_operation
def apply_wiki_mirror(
    conn: Any,
    pages: list[dict],
    links: dict[str, list[str]],
    fs_rel_paths: list[str],
    dry_run: bool,
) -> dict:
    """Passes 1 to 4 on one connection: upsert pages (stale memory ids
    dropped), refresh [[slug]] links, resolve stragglers, purge ghosts; then
    roll back a dry run or commit."""
    id_by_rel, written, unchanged, errors = _upsert_pages(conn, pages)
    links_written, link_errors = _upsert_links(conn, id_by_rel, links)
    resolved = resolve_unresolved_links(conn)
    purge = purge_ghost_pages(conn, fs_rel_paths, dry_run=dry_run)
    # source: ADR-0463
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return {
        "pages_written": written,
        "pages_unchanged": unchanged,
        "links_written": links_written,
        "links_resolved_pass3": resolved,
        "purge": purge,
        "errors": errors + link_errors,
    }
