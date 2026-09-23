"""Backfill pass: reclassify historical ``memories.write_class`` rows
still at the migration's DEFAULT sentinel (M-D2, 7.4).

One-shot migration pass, not wired into ``consolidate``: every writer as
of 7.4 sets ``write_class`` explicitly at insert time
(``mcp_server.shared.write_class`` module docstring — full writer
inventory); this pass drains the pre-existing stock the schema migration
left at its safe DEFAULT. Invoked by ``scripts/backfill_write_class.py``.

source: ADR-0381"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.shared.write_class import DELIBERATE, classify_write_class
from mcp_server.infrastructure.pg_store_memory_write_class import (
    bulk_reclassify_source,
    list_source_groups_at_default,
)

logger = logging.getLogger(__name__)

# source: ADR-0381
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
        # source: ADR-0381
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

    source: ADR-0381"""

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
