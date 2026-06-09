"""Wiki maintenance cycle — runs on every ``consolidate`` invocation.

The wiki has to stay up to date without a human in the loop. Two
maintenance moves run here:

  1. **Purge** — delete pages that fail the current classifier (audit
     tags, hard negatives) AND pages that are majority placeholder
     stubs. Existing pages get the same treatment as freshly written
     ones; nothing the system itself produced gets a free pass.

  2. **Queue authoring jobs** — call the auto-curator to compute how
     many coverage-driven jobs (missing scopes) + cluster-driven jobs
     (heat clusters) are pending. The count surfaces in the
     ``consolidate`` return payload and the SessionStart preamble so
     the next interactive LLM (Opus 4.7 in the user's session) picks
     up the work without being asked.

Both moves are wrapped in try/except — failure here must never break
``consolidate`` itself, because consolidate runs other essential
memory maintenance that mustn't be blocked by a wiki edge case.

Source for the policy: user direction 2026-05-18 — "It should be
running without a human in the loop, and wiki should be always up to
date. Existing documentation should be processed the same way as new
documentation and fixed the same way."
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _headless_authoring_enabled() -> bool:
    """Opt-in gate for the ``claude -p`` headless authoring drain.

    Default OFF. The drain can spawn up to ~38 ``claude -p`` subprocesses
    per cycle (30 anchor + 8 file-doc), each up to 180s, **synchronously
    on the consolidate event loop**. Unthrottled, that storm wedges the
    machine — and in tests/CI (where ``claude`` may be on PATH on dev
    boxes) it also blocks the suite. It stays off until per-cycle load
    balancing lands; set ``CORTEX_HEADLESS_AUTHORING=1`` to opt in.
    """
    return os.getenv("CORTEX_HEADLESS_AUTHORING", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Autonomous mode applies the stub + classifier purge axes — these
# remove content that is either placeholder-only or doesn't pass
# admission. **Shallow pages are NEVER auto-deleted** (user direction
# 2026-05-18: "Removing is not a solution. Fixing the curation by
# showing information that should be present and missing for each
# file is a curation of the documentation."). Instead, shallow pages
# are surfaced as curation gaps — visible to the reader on the page
# itself and queued as re-author jobs for the LLM to fill in.
_AUTONOMOUS_STUB_APPLY_DEFAULT = True
_AUTONOMOUS_CLASSIFIER_APPLY_DEFAULT = True
_AUTONOMOUS_SHALLOW_APPLY_DEFAULT = False  # NEVER delete; queue for re-author

# Per-cycle deletion cap. Tuned so the worst case — a classifier bug
# misclassifying every page as a reject — costs one cap's worth of
# pages before the next cycle exposes the regression in
# ``stats.wiki.classifier.purged`` (and the operator restores from git
# / backup if needed). A bigger cap accelerates legitimate cleanup; a
# smaller cap reduces the blast radius of a bug. 500 is the conservative
# middle: ~3 weeks to clear a 9k backlog, vs. one bad cycle losing 500.
MAX_PURGES_PER_CYCLE = 500


async def _invoke_wiki_purge(args: dict[str, Any]) -> dict[str, Any]:
    """Await the wiki_purge handler on the caller's event loop."""
    from mcp_server.handlers.wiki_purge import handler as wiki_purge_handler

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
    ``pending_total``).
    """
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
    except Exception as exc:
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
    except Exception as exc:
        logger.warning("wiki_maintenance: classifier purge failed (non-fatal): %s", exc)
        if out["status"] == "ok":
            out["status"] = f"classifier_error: {type(exc).__name__}: {exc}"

    # Headless authoring drain (Meadows L10 actuator). The previous
    # design queued jobs that only drained when the user opened a
    # session. The worker here calls `claude -p` directly so the
    # loop closes without human intervention. See
    # ``consolidation/headless_authoring.py``.
    #
    # Opt-in only (default OFF): the drain spawns up to ~38 ``claude -p``
    # subprocesses synchronously on the event loop. Until per-cycle load
    # balancing lands it stays gated behind ``CORTEX_HEADLESS_AUTHORING``
    # so consolidate (and the test suite) never blocks on a subprocess
    # storm.
    if not _headless_authoring_enabled():
        out["headless_authoring"] = {"status": "disabled"}
    else:
        try:
            from mcp_server.handlers.consolidation.headless_authoring import (
                run_headless_authoring_cycle,
            )

            cycle = run_headless_authoring_cycle()
            out["headless_authoring"] = {
                "pages_with_gaps": cycle.pages_with_gaps,
                "drains_attempted": cycle.drains_attempted,
                "drains_filled": cycle.drains_filled,
                "drains_failed": cycle.drains_failed,
                "duration_ms": cycle.duration_ms,
            }
        except Exception as exc:
            logger.debug(
                "wiki_maintenance: headless authoring drain failed (non-fatal): %s",
                exc,
            )
            out["headless_authoring"] = {
                "status": f"error: {type(exc).__name__}: {exc}",
            }

    # Per-project coverage dashboards (Meadows L6 information surface).
    try:
        from mcp_server.core.wiki_coverage_dashboard import write_dashboards
        from mcp_server.infrastructure.config import WIKI_ROOT as _WR

        dashboards = write_dashboards(str(_WR))
        out["dashboards"] = {
            "written": len(dashboards),
            "projects": sorted(dashboards.keys())[:20],
        }
    except Exception as exc:
        logger.debug("wiki_maintenance: dashboard render failed (non-fatal): %s", exc)
        out["dashboards"] = {"status": f"error: {type(exc).__name__}: {exc}"}

    # Curation backlog.
    try:
        from mcp_server.core.auto_curator import count_pending_clusters_streamed
        from mcp_server.core.wiki_coverage import (
            _project_source_root,
            audit_all_domains,
            audit_all_file_coverage,
        )
        from mcp_server.core.wiki_drift import audit_wiki_drift
        from mcp_server.infrastructure.config import WIKI_ROOT

        chunks = (
            store.iter_memories_for_decay()
            if hasattr(store, "iter_memories_for_decay")
            else [store.get_all_memories_for_decay()]
        )
        out["cluster_jobs"] = count_pending_clusters_streamed(
            chunks, wiki_root=str(WIKI_ROOT)
        )
        coverages = audit_all_domains(str(WIKI_ROOT))
        out["coverage_gaps"] = sum(c.missing_count for c in coverages)
        # File-level coverage: count files that aren't referenced
        # anywhere in the wiki. Aggregated across every domain that has
        # a resolvable source root. This is "nothing left uncovered"
        # measured at the file granularity.
        file_rolls = audit_all_file_coverage(str(WIKI_ROOT))
        out["uncovered_files"] = sum(
            r.source_file_count - r.covered_file_count for r in file_rolls
        )
        out["file_coverage_by_domain"] = [
            {
                "domain": r.domain,
                "covered": r.covered_file_count,
                "total": r.source_file_count,
                "ratio": round(r.coverage_ratio, 3),
            }
            for r in file_rolls
        ]
        # Drift: existing pages out of sync with the code or
        # off-template. Capped at 1000 entries — a wide-open drift
        # backlog doesn't need to materialise in full here; the
        # curate_wiki call can re-enumerate when it needs the actual
        # job set.
        drifts = audit_wiki_drift(str(WIKI_ROOT), _project_source_root, limit=1000)
        out["drifted_pages"] = len(drifts)
        out["pending_total"] = (
            out["cluster_jobs"]
            + out["coverage_gaps"]
            + out["uncovered_files"]
            + out["drifted_pages"]
        )
    except Exception as exc:
        logger.debug("wiki_maintenance: backlog count failed (non-fatal): %s", exc)
        if out["status"] == "ok":
            out["status"] = f"backlog_error: {type(exc).__name__}: {exc}"

    return out
