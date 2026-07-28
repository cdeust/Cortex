"""Backfill pass: reclassify historical ``memories.write_class`` rows
still at the migration's DEFAULT sentinel (M-D2, 7.4).

Composition root — wires ``core.write_class.classify_write_class`` (the
single classification choke point, source-only fallback path) to
infrastructure (``pg_store_memory_write_class``'s group scan and bulk
UPDATE). Mirrors ``memory_domain_backfill_pass.py``'s split (I6-D3
precedent): pure decision in core, I/O in infrastructure, wiring here.

One-shot migration pass, not wired into ``consolidate``: every writer as
of 7.4 sets ``write_class`` explicitly at insert time
(``mcp_server.core.write_class`` module docstring — full writer
inventory); this pass drains the pre-existing stock the schema migration
left at its safe DEFAULT. Invoked by ``scripts/backfill_write_class.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.write_class import DELIBERATE, classify_write_class
from mcp_server.infrastructure.pg_store_memory_write_class import (
    bulk_reclassify_source,
    list_source_groups_at_default,
)

logger = logging.getLogger(__name__)

# Per-run cap on DISTINCT source groups scanned (not row count — one
# group's bulk UPDATE can touch many rows in a single statement). Measured
# DB source cardinality across the whole M-D2 taxonomy is in the low
# thousands (backfill:<slug> per scanned directory, wiki://<rel_path> per
# wiki page) — comfortably under this cap in one pass; a second
# invocation is a no-op by construction if the stock ever exceeds it
# (list_source_groups_at_default only returns groups still at the
# sentinel).
DEFAULT_WRITE_CLASS_BACKFILL_LIMIT = 5000


def _process_source_group(
    conn: Any,
    row: dict[str, Any],
    *,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Reclassify one source group, journaling only actual changes."""

    source = row["source"]
    row_count = row["row_count"]
    target = classify_write_class({"source": source})

    if target == DELIBERATE:
        # Already the sentinel's own value — genuinely deliberate content
        # (or a source classify_write_class has no rule for), nothing to
        # change. Not journaled: the volume of "correctly deliberate"
        # groups dwarfs the volume of actual reclassifications, and
        # journaling every scanned group (mirroring memory_domain_backfill's
        # per-row journal) would make this pass's output unusable at the
        # measured source cardinality.
        out["unchanged_groups"] += 1
        return

    changed = row_count
    if apply:
        changed = bulk_reclassify_source(conn, source, target)

    out["reclassified_groups"] += 1
    out["reclassified_rows"] += changed
    out["by_target_class"][target] = out["by_target_class"].get(target, 0) + changed
    out["journal"].append(
        {
            "source": source,
            "from": DELIBERATE,
            "to": target,
            "row_count": changed,
        }
    )


async def run_write_class_backfill_pass(
    store: Any,
    *,
    apply: bool = False,
    limit: int = DEFAULT_WRITE_CLASS_BACKFILL_LIMIT,
) -> dict[str, Any]:
    """Reclassify every active source group still at the DEFAULT sentinel.

    Pre-condition:  ``store`` exposes ``batch_pool``
                    (``psycopg_pool.ConnectionPool``), matching how
                    ``consolidate`` and ``memory_domain_backfill_pass``
                    already borrow connections for maintenance sweeps.
    Post-condition: for every scanned DISTINCT ``source`` group among
                    active rows still at ``write_class = 'deliberate'``
                    (the migration's DEFAULT — ``infrastructure/
                    pg_schema.py`` MIGRATIONS_DDL), where
                    ``core.write_class.classify_write_class`` resolves
                    that source to a DIFFERENT class, every matching row
                    now has ``write_class`` equal to that class IFF
                    ``apply`` is True — a single bulk UPDATE per group,
                    re-guarded at the SQL layer against a group that
                    genuinely belongs at ``deliberate`` (no-op) so this
                    pass can NEVER touch a row a post-7.4 writer already
                    classified explicitly to something other than the
                    sentinel. ``apply=False`` performs the same scan and
                    classification without writing (dry run) — the
                    returned counts and journal are identical either way
                    (mirrors ``memory_domain_backfill_pass``'s dry-run
                    contract), except ``journal[*].row_count`` reports the
                    row count observed at scan time rather than the
                    UPDATE's actual rowcount (dry-run has no UPDATE to
                    report from). Idempotent: a second run after
                    ``apply=True`` finds zero groups whose current
                    ``write_class`` differs from
                    ``classify_write_class(source)`` (every reclassified
                    group is no longer at the sentinel; every group left
                    at the sentinel genuinely resolves to ``deliberate``),
                    so it reclassifies nothing.
    """

    out: dict[str, Any] = {
        "scanned_groups": 0,
        "unchanged_groups": 0,
        "reclassified_groups": 0,
        "reclassified_rows": 0,
        "by_target_class": {},
        "journal": [],
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            rows = list_source_groups_at_default(conn, limit)
            out["scanned_groups"] = len(rows)
            for row in rows:
                _process_source_group(conn, row, apply=apply, out=out)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("write_class_backfill_pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out


__all__ = [
    "DEFAULT_WRITE_CLASS_BACKFILL_LIMIT",
    "run_write_class_backfill_pass",
]
