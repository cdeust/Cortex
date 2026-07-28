"""Backfill pass: derive + persist primary wiki page -> source-file links
for pages whose frontmatter never declared one (ADR-0051 STEP 3).

Composition root — wires ``core.wiki_source_backfill`` (pure derivation)
to infrastructure (DB reads/writes via ``pg_store_wiki_sources`` /
``pg_store_wiki_thermo``, filesystem existence checks via
``wiki_drift._file_exists_under``) under ``run_wiki_maintenance``'s
non-fatal try/except contract. Split out of ``wiki_maintenance.py`` to
keep both files under the 300-line cap (coding-standards.md §4.1).

Scope: strictly the primary ``'documents'`` link_kind. Persisting
``'references'`` (the per-page cited-symbol graph ``wiki_consolidate``
already computes and discards) is Étape 4 — out of scope here.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from mcp_server.core.wiki_drift import _file_exists_under
from mcp_server.core.wiki_coverage import _project_source_root
from mcp_server.core.wiki_source_backfill import derive_primary_source
from mcp_server.infrastructure.pg_store_wiki_sources import (
    upsert_page_sources,
    list_pages_missing_source_link,
)
from mcp_server.infrastructure.pg_store_wiki_thermo import get_claim_file_refs_for_pages

logger = logging.getLogger(__name__)

# Per-cycle scan cap — mirrors MAX_PURGES_PER_CYCLE's rationale in
# wiki_maintenance.py: bounds one consolidate cycle's cost; pages left
# over are picked up by the next cycle (list_pages_missing_source_link
# only returns pages that are STILL unlinked, so nothing is skipped).
DEFAULT_BACKFILL_LIMIT = 500


def _build_exists_fn(source_root: str | None) -> Callable[[str], bool]:
    if source_root is None:
        return lambda _path: False

    return lambda path: _file_exists_under(source_root, path)


def _resolve_source_root(domain: str) -> str | None:

    return _project_source_root(domain)


def _process_one_page(
    conn: Any,
    page: dict[str, Any],
    claim_files: list[str],
    *,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Derive one page's primary source and, if found, persist it."""

    exists_fn = _build_exists_fn(_resolve_source_root(str(page.get("domain") or "")))
    result = derive_primary_source(page, claim_files, exists_fn)
    if result is None:
        return
    path, tag = result
    out["by_source"][tag] = out["by_source"].get(tag, 0) + 1
    out["primaries_written"] += 1
    if not apply:
        return
    upsert_page_sources(conn, page["id"], [path], link_kind="documents", source=tag)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wiki.pages SET documents_primary = %s WHERE id = %s",
            (path, page["id"]),
        )


async def run_source_backfill_pass(
    store: Any, *, apply: bool = True, limit: int = DEFAULT_BACKFILL_LIMIT
) -> dict[str, Any]:
    """Derive and persist ``documents_primary`` for pages that lack one.

    Pre-condition:  ``store`` exposes ``batch_pool``
                    (``psycopg_pool.ConnectionPool``) — the long-running
                    writer pool, matching how ``consolidate`` already
                    borrows connections for other maintenance sweeps.
    Post-condition: for every scanned page where
                    ``core.wiki_source_backfill.derive_primary_source``
                    finds an unambiguous candidate, ``wiki.page_sources``
                    carries one ``link_kind='documents'`` row for that
                    page and ``wiki.pages.documents_primary`` equals that
                    path, IFF ``apply`` is True. ``apply=False`` performs
                    the same derivation without writing (dry run) — the
                    returned counts are identical either way.
    """

    out: dict[str, Any] = {
        "pages_scanned": 0,
        "primaries_written": 0,
        "by_source": {},
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            pages = list_pages_missing_source_link(conn, limit=limit)
            out["pages_scanned"] = len(pages)
            if not pages:
                return out
            claim_refs = get_claim_file_refs_for_pages(conn, [p["id"] for p in pages])
            for page in pages:
                _process_one_page(
                    conn, page, claim_refs.get(page["id"], []), apply=apply, out=out
                )
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("wiki_source_backfill_pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out
