"""Curation-backlog count for ``run_wiki_maintenance``.

Split out of ``wiki_maintenance.py`` to keep both files under the
300-line cap (coding-standards.md §4.1) — no logic changed from what
previously lived inline in that module's "Curation backlog" block.

Composition root — wires ``core.auto_curator`` / ``core.wiki_coverage`` /
``core.wiki_drift`` (pure logic) to the memory store's decay-chunk
iterator and the filesystem wiki root.

G-2 grooming (2026-07-11): also reports the ``lesson_promotion``
candidate backlog (mechanical ``COUNT(*)``, ~76ms measured, zero
judgment — see ``pg_store_lesson_promotion.count_lesson_promotion_
candidates``'s docstring). ``curate_distill``'s backlog is deliberately
NOT reported here: its ``total_dossiers_eligible`` requires running the
same entity/co-access clustering the full job-building handler runs
(measured ~2.6s against the dev corpus, dominated by
``core.auto_curator.build_clusters`` over a 500-memory pool) — there is
no cheap ``COUNT(*)`` path for it without duplicating that clustering
work, and running it on every consolidate cycle (up to 47/day measured,
``consolidation_log``) would add tens of seconds of egress per day for
a number nobody acts on without calling the tool anyway. Call
``curate_distill`` directly for that count; it does its own accounting.
"""

from __future__ import annotations

import logging
from typing import Any
from mcp_server.observability import silent_failure
from mcp_server.infrastructure.pg_store_lesson_promotion import (
    count_lesson_promotion_candidates,
)
from mcp_server.core.auto_curator import count_pending_clusters_streamed
from mcp_server.core.wiki_coverage import (
    _project_source_root,
    audit_all_domains,
    audit_all_file_coverage,
    domain_coverage_missing_count,
    file_coverage_coverage_ratio,
)
from mcp_server.core.wiki_drift import audit_wiki_drift
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.wiki_page_fs import build_wiki_page_port

logger = logging.getLogger(__name__)


def _lesson_promotion_backlog(store: Any) -> int | None:
    """Best-effort lesson-promotion candidate count; ``None`` on failure.

    Precondition: none — degrades to ``None`` (not 0, so a caller can't
    mistake "query failed" for "queue is empty") when ``store`` lacks
    ``batch_pool`` (SQLite fallback in tests) or the query itself fails.
    Postcondition: returns the exact eligible-candidate count on
    success; never raises.
    """

    try:
        with store.batch_pool.connection() as conn:
            return count_lesson_promotion_candidates(conn)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("wiki_backlog_pass.lesson_promotion_backlog")
        silent_failure.note("wiki_backlog_pass.lesson_promotion_backlog", exc)
        return None


async def run_backlog_pass(store: Any) -> dict[str, Any]:
    """Count pending coverage/cluster/drift jobs across the whole wiki.

    Pre-condition:  ``store`` exposes ``iter_memories_for_decay`` (or,
                    failing that, ``get_all_memories_for_decay``).
    Post-condition: returned dict carries ``cluster_jobs``,
                    ``coverage_gaps``, ``uncovered_files``,
                    ``file_coverage_by_domain``, ``drifted_pages``,
                    ``lesson_promotion_backlog`` (int or ``None`` on a
                    degraded read — see ``_lesson_promotion_backlog``),
                    and ``pending_total`` (the sum of the first four
                    count fields — unchanged shape; ``lesson_promotion_
                    backlog`` is intentionally excluded from this sum,
                    it is a distinct queue with a distinct consumer
                    tool, not a wiki-authoring job) — read-only, no rows
                    written.
    """

    out: dict[str, Any] = {}
    chunks = (
        store.iter_memories_for_decay()
        if hasattr(store, "iter_memories_for_decay")
        else [store.get_all_memories_for_decay()]
    )
    out["cluster_jobs"] = count_pending_clusters_streamed(
        chunks, wiki_page_port=build_wiki_page_port(str(WIKI_ROOT))
    )

    coverages = audit_all_domains(str(WIKI_ROOT))
    out["coverage_gaps"] = sum(domain_coverage_missing_count(c) for c in coverages)

    # File-level coverage: count files that aren't referenced anywhere
    # in the wiki. Aggregated across every domain that has a resolvable
    # source root. This is "nothing left uncovered" measured at the
    # file granularity.
    file_rolls = audit_all_file_coverage(str(WIKI_ROOT))
    out["uncovered_files"] = sum(
        r.source_file_count - r.covered_file_count for r in file_rolls
    )
    out["file_coverage_by_domain"] = [
        {
            "domain": r.domain,
            "covered": r.covered_file_count,
            "total": r.source_file_count,
            "ratio": round(file_coverage_coverage_ratio(r), 3),
        }
        for r in file_rolls
    ]

    # Drift: existing pages out of sync with the code or off-template.
    # Capped at 1000 entries — a wide-open drift backlog doesn't need
    # to materialise in full here; the curate_wiki call can
    # re-enumerate when it needs the actual job set.
    drifts = audit_wiki_drift(str(WIKI_ROOT), _project_source_root, limit=1000)
    out["drifted_pages"] = len(drifts)

    # Mechanical report only (G-2) — never folded into pending_total,
    # see this module's docstring and _lesson_promotion_backlog.
    out["lesson_promotion_backlog"] = _lesson_promotion_backlog(store)

    out["pending_total"] = (
        out["cluster_jobs"]
        + out["coverage_gaps"]
        + out["uncovered_files"]
        + out["drifted_pages"]
    )
    return out
