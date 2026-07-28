"""Backfill pass: re-derive the true project domain for wiki pages stuck
in a catch-all bucket (``uncategorized``, ``_general``, ``global``, ...).

Composition root — wires ``core.wiki_domain_backfill`` (pure majority-
vote derivation) to infrastructure (DB reads/writes via
``pg_store_wiki_domain``, repo-registry lookups via
``shared.domain_mapping``, filesystem containment checks) under
``run_wiki_maintenance``'s non-fatal try/except contract. Split out as
its own module to keep ``wiki_maintenance.py`` under the 300-line cap
(coding-standards.md §4.1).

Volet 4 of the wiki data-quality cleanup (ADR-0051 family): the
``documents`` primary-source backfill (Étape 3 / ``wiki_source_backfill``)
closes the missing-link gap; this pass closes the wrong-domain gap using
the same source-path evidence.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Per-cycle scan cap — mirrors DEFAULT_BACKFILL_LIMIT's rationale in
# wiki_source_backfill_pass.py: bounds one consolidate cycle's cost;
# pages left over are picked up by the next cycle (list_catchall_pages_
# with_sources only returns pages whose domain is STILL unregistered).
DEFAULT_DOMAIN_BACKFILL_LIMIT = 500


def _registry_domain_roots() -> dict[str, list[str]]:
    """Map each registered canonical domain to its checkout root(s).

    Several repos can share one ``canonical`` (a repo family); each of
    their filesystem roots is a valid containment root for that domain.
    """
    from mcp_server.shared.domain_mapping import _build_registry

    registry = _build_registry()
    roots: dict[str, list[str]] = {}
    for repo in registry.repos:
        if not repo.canonical or not repo.fs_path:
            continue
        roots.setdefault(repo.canonical, []).append(repo.fs_path)
    return roots


def _domains_containing(domain_roots: dict[str, list[str]], rel_path: str) -> set[str]:
    """Domains whose checkout contains a real file at ``rel_path``.

    A domain votes at most once even if it owns multiple roots; the
    ``any`` over its roots keeps the containment test one level deep.
    """
    hits: set[str] = set()
    for domain, roots in domain_roots.items():
        if any(os.path.exists(os.path.join(root, rel_path)) for root in roots):
            hits.add(domain)
    return hits


def _build_containment_fn(
    domain_roots: dict[str, list[str]],
) -> Callable[[str], set[str]]:
    """Bind ``domain_roots`` into the ``domains_containing`` fn core needs."""
    return lambda rel_path: _domains_containing(domain_roots, rel_path)


def _process_page(
    conn: Any,
    page: dict[str, Any],
    containing: Callable[[str], set[str]],
    *,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Derive one page's true domain and, if it differs, persist it."""
    from mcp_server.core.wiki_domain_backfill import derive_page_domain
    from mcp_server.infrastructure.pg_store_wiki_domain import update_page_domain

    domain = derive_page_domain(page["source_paths"], containing)
    if domain is None or domain == page["domain"]:
        return
    out["domains_reassigned"] += 1
    out["by_domain"][domain] = out["by_domain"].get(domain, 0) + 1
    if apply:
        update_page_domain(conn, page["id"], domain)


async def run_domain_backfill_pass(
    store: Any, *, apply: bool = True, limit: int = DEFAULT_DOMAIN_BACKFILL_LIMIT
) -> dict[str, Any]:
    """Re-derive and persist the true domain for catch-all wiki pages.

    Pre-condition:  ``store`` exposes ``batch_pool``
                    (``psycopg_pool.ConnectionPool``) — the long-running
                    writer pool, matching how ``consolidate`` already
                    borrows connections for other maintenance sweeps.
    Post-condition: for every scanned page where
                    ``core.wiki_domain_backfill.derive_page_domain``
                    finds an unambiguous majority domain that differs
                    from the page's current domain, ``wiki.pages.domain``
                    equals that derived domain, IFF ``apply`` is True.
                    ``apply=False`` performs the same derivation without
                    writing (dry run) — the returned counts are
                    identical either way.
    """
    from mcp_server.infrastructure.pg_store_wiki_domain import (
        list_catchall_pages_with_sources,
    )

    out: dict[str, Any] = {
        "pages_scanned": 0,
        "domains_reassigned": 0,
        "by_domain": {},
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            domain_roots = _registry_domain_roots()
            containing = _build_containment_fn(domain_roots)
            pages = list_catchall_pages_with_sources(
                conn, list(domain_roots), limit=limit
            )
            out["pages_scanned"] = len(pages)
            for page in pages:
                _process_page(conn, page, containing, apply=apply, out=out)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("wiki_domain_backfill_pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out
