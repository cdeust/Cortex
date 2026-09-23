"""Curation-backlog count for ``run_wiki_maintenance``.

Composition root — wires ``core.auto_curator`` / ``core.wiki_coverage`` /
``core.wiki_drift`` (pure logic) to the memory store's decay-chunk
iterator and the filesystem wiki root.

source: ADR-0376"""

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

    Callable only when ``store.batch_pool`` exists: ``run_wiki_maintenance``
    is this function's sole caller and gates it on that capability once,
    at wiring time (issue #636) — this is a PostgreSQL-only table, and the
    SQLite backend never reaches this function at all.
    Precondition: ``store`` exposes ``batch_pool``.
    Postcondition: returns the exact eligible-candidate count on success;
    degrades to ``None`` (not 0, so a caller can't mistake "query failed"
    for "queue is empty") when the query itself fails; never raises.
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
                    ``file_coverage_by_domain``, ``drifted_pages``, and
                    ``pending_total`` (the sum of those four count
                    fields) — read-only, no rows written.
                    ``lesson_promotion_backlog`` is NOT part of this
                    dict: it is a PostgreSQL-only queue (see
                    ``_lesson_promotion_backlog``) that
                    ``run_wiki_maintenance`` populates itself, directly,
                    only on a PostgreSQL-backed store (issue #636).
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

    # source: ADR-0376
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

    out["pending_total"] = (
        out["cluster_jobs"]
        + out["coverage_gaps"]
        + out["uncovered_files"]
        + out["drifted_pages"]
    )
    return out
