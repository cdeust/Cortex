"""Wiki maintenance cycle — runs on every ``consolidate`` invocation.

The wiki has to stay up to date without a human in the loop. Two
maintenance moves run here:

source: ADR-0379"""

from __future__ import annotations

import logging
import os
from typing import Any
from mcp_server.handlers.wiki_purge import handler as wiki_purge_handler
from mcp_server.handlers.consolidation.headless_authoring import (
    run_headless_authoring_cycle,
)
from mcp_server.core.wiki_coverage_dashboard import write_dashboards
from mcp_server.infrastructure.config import WIKI_ROOT as _WR
from mcp_server.handlers.consolidation.wiki_source_backfill_pass import (
    run_source_backfill_pass,
)
from mcp_server.handlers.consolidation.wiki_domain_backfill_pass import (
    run_domain_backfill_pass,
)
from mcp_server.handlers.consolidation.wiki_citation_seed_pass import (
    DEFAULT_SEED_SCAN_LIMIT,
    run_wiki_citation_seed_pass,
)
from mcp_server.handlers.consolidation.wiki_backlog_pass import run_backlog_pass

logger = logging.getLogger(__name__)


def _headless_authoring_enabled() -> bool:
    """Opt-in gate for the ``claude -p`` headless authoring drain.

        Default OFF. Even with concurrency + budget throttling now in place,
        each cycle spends a real ``claude -p`` budget (subscription quota by
        default, or the API if opted in) and is therefore opt-in. Set
        ``CORTEX_HEADLESS_AUTHORING=1`` to enable.

    source: ADR-0379"""
    return os.getenv("CORTEX_HEADLESS_AUTHORING", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# source: ADR-0379
_AUTONOMOUS_STUB_APPLY_DEFAULT = True
_AUTONOMOUS_CLASSIFIER_APPLY_DEFAULT = True
_AUTONOMOUS_SHALLOW_APPLY_DEFAULT = False  # NEVER delete; queue for re-author

# source: ADR-0379
MAX_PURGES_PER_CYCLE = 500


async def _invoke_wiki_purge(args: dict[str, Any]) -> dict[str, Any]:
    """Await the wiki_purge handler on the caller's event loop."""

    return await wiki_purge_handler(args)


async def _run_purge_axis(
    *, axis: str, apply: bool, max_purges: int | None = None
) -> dict[str, Any]:
    """Run wiki_purge with exactly one axis enabled, returning a flat dict.

    Awaited directly on the consolidate handler's event loop. An earlier
    revision bridged via ``asyncio.run_coroutine_threadsafe(...).result()``,
    which self-deadlocked: it scheduled the coroutine on the *same* loop
    whose thread the synchronous caller had already blocked, so the
    coroutine could never run and every axis stalled to the 120s timeout
    (CI Test job hung ~1h). Awaiting keeps the psycopg async pool on its
    owning loop and removes the deadlock entirely.
    """
    purge_args: dict[str, Any] = {
        "apply": apply,
        "purge_stubs": axis == "stub",
        "purge_shallow": axis == "shallow",
        "purge_classifier_rejects": axis == "classifier",
    }
    if max_purges is not None:
        purge_args["max_purges"] = max_purges
    return await _invoke_wiki_purge(purge_args)


async def run_wiki_maintenance(
    store: Any,
    *,
    apply_stubs: bool = _AUTONOMOUS_STUB_APPLY_DEFAULT,
    apply_classifier_rejects: bool = _AUTONOMOUS_CLASSIFIER_APPLY_DEFAULT,
    max_purges_per_axis: int | None = MAX_PURGES_PER_CYCLE,
    source_backfill_dry_run: bool = False,
    domain_backfill_dry_run: bool = False,
    apply_citation_seed: bool = True,
    citation_seed_limit: int | None = None,
) -> dict[str, Any]:
    """Purge stale wiki pages and report the curation backlog.

        Two axes, BOTH applied by default — the system decides, no human in
        the loop. ``max_purges_per_axis`` (default 500) caps each axis's
        per-cycle deletion so a buggy classifier change can't wipe the wiki
        in one shot; remaining pages are deferred to the next cycle. Pass
        ``max_purges_per_axis=None`` to disable the cap (one-shot sweeps).

          * **stubs** — placeholder-only pages.
          * **classifier_rejects** — pages that no longer pass the current
            admission gate.

        Returns a dict with one stanza per axis (``stub`` / ``classifier``)
        each carrying ``{applied, purged, deferred, cap_reached, ...}`` plus
        a backlog stanza (``coverage_gaps``, ``cluster_jobs``,
        ``pending_total``, ``lesson_promotion_backlog``), a
        ``source_backfill`` stanza (``{pages_scanned, primaries_written,
        by_source, status}``), a ``domain_backfill`` stanza
        (``{pages_scanned, domains_reassigned, by_domain, status}``), and a
        ``citation_seed`` stanza (``{scanned_rows, seeded, already_cited,
        skipped_race, journal, status}``).

    source: ADR-0379"""
    out: dict[str, Any] = {
        "stub": {
            "applied": apply_stubs,
            "purged": 0,
            "deferred": 0,
            "placeholder_lines_purged": 0,
        },
        "classifier": {
            "applied": apply_classifier_rejects,
            "purged": 0,
            "deferred": 0,
        },
        "max_purges_per_axis": max_purges_per_axis,
        "coverage_gaps": 0,
        "cluster_jobs": 0,
        "pending_total": 0,
        "status": "ok",
    }

    # Stub axis.
    try:
        r = await _run_purge_axis(
            axis="stub", apply=apply_stubs, max_purges=max_purges_per_axis
        )
        out["stub"]["purged"] = r.get("purged", 0)
        out["stub"]["deferred"] = r.get("deferred", 0)
        out["stub"]["placeholder_lines_purged"] = r.get("placeholder_lines_purged", 0)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("wiki_maintenance: stub purge failed (non-fatal): %s", exc)
        out["status"] = f"stub_error: {type(exc).__name__}: {exc}"

    # Classifier axis.
    try:
        r = await _run_purge_axis(
            axis="classifier",
            apply=apply_classifier_rejects,
            max_purges=max_purges_per_axis,
        )
        out["classifier"]["purged"] = r.get("purged", 0)
        out["classifier"]["deferred"] = r.get("deferred", 0)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("wiki_maintenance: classifier purge failed (non-fatal): %s", exc)
        if out["status"] == "ok":
            out["status"] = f"classifier_error: {type(exc).__name__}: {exc}"

    # source: ADR-0379
    if not _headless_authoring_enabled():
        out["headless_authoring"] = {"status": "disabled"}
    else:
        try:
            cycle = await run_headless_authoring_cycle()
            out["headless_authoring"] = {
                "pages_with_gaps": cycle.pages_with_gaps,
                "drains_attempted": cycle.drains_attempted,
                "drains_filled": cycle.drains_filled,
                "drains_failed": cycle.drains_failed,
                "duration_ms": cycle.duration_ms,
                "usd_spent": cycle.usd_spent,
                "wall_clock_ms": cycle.wall_clock_ms,
                "skipped_budget": cycle.skipped_budget,
            }
        except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.debug(
                "wiki_maintenance: headless authoring drain failed (non-fatal): %s",
                exc,
            )
            out["headless_authoring"] = {
                "status": f"error: {type(exc).__name__}: {exc}",
            }

    # Per-project coverage dashboards (Meadows L6 information surface).
    try:
        dashboards = write_dashboards(str(_WR))
        out["dashboards"] = {
            "written": len(dashboards),
            "projects": sorted(dashboards.keys())[:20],
        }
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("wiki_maintenance: dashboard render failed (non-fatal): %s", exc)
        out["dashboards"] = {"status": f"error: {type(exc).__name__}: {exc}"}

    # source: ADR-0379
    try:
        out["source_backfill"] = await run_source_backfill_pass(
            store, apply=not source_backfill_dry_run
        )
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("wiki_maintenance: source backfill failed (non-fatal): %s", exc)
        out["source_backfill"] = {"status": f"error: {type(exc).__name__}: {exc}"}
        if out["status"] == "ok":
            out["status"] = f"source_backfill_error: {type(exc).__name__}: {exc}"

    # Domain backfill (Volet 4): re-derives true domain for catch-all pages.
    try:
        out["domain_backfill"] = await run_domain_backfill_pass(
            store, apply=not domain_backfill_dry_run
        )
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("wiki_maintenance: domain backfill failed (non-fatal): %s", exc)
        out["domain_backfill"] = {"status": f"error: {type(exc).__name__}: {exc}"}
        if out["status"] == "ok":
            out["status"] = f"domain_backfill_error: {type(exc).__name__}: {exc}"

    # source: ADR-0379
    try:
        out["citation_seed"] = await run_wiki_citation_seed_pass(
            store,
            apply=apply_citation_seed,
            limit=citation_seed_limit or DEFAULT_SEED_SCAN_LIMIT,
        )
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning(
            "wiki_maintenance: citation seed pass failed (non-fatal): %s", exc
        )
        out["citation_seed"] = {"status": f"error: {type(exc).__name__}: {exc}"}
        if out["status"] == "ok":
            out["status"] = f"citation_seed_error: {type(exc).__name__}: {exc}"

    # Curation backlog.
    try:
        out.update(await run_backlog_pass(store))
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("wiki_maintenance: backlog count failed (non-fatal): %s", exc)
        if out["status"] == "ok":
            out["status"] = f"backlog_error: {type(exc).__name__}: {exc}"

    return out
