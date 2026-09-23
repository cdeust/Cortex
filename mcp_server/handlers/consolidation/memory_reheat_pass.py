"""Deliberate-heat recalibration pass: one-shot raise of ``heat_base`` for
active deliberate memories below the measured retrieval cliff (I6-D5,
INC6.6).

source: ADR-0368"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.memory_reheat import DEFAULT_REHEAT_TARGET, compute_reheat_target
from mcp_server.infrastructure.pg_store_memory_reheat import (
    apply_reheat,
    list_deliberate_below_target,
)

logger = logging.getLogger(__name__)

# Mirrors pg_store_memory_reheat.DEFAULT_REHEAT_SCAN_LIMIT — re-exported so
# callers of this handler don't need to reach into infrastructure.
DEFAULT_REHEAT_SCAN_LIMIT = 5000


def _process_row(
    conn: Any,
    row: dict[str, Any],
    *,
    target: float,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Decide and (optionally) apply one row's heat_base raise, journaling it."""

    decision = compute_reheat_target(
        heat_base_before=row["heat_base"],
        effective_heat_before=row["effective_heat"],
        effective_heat_at_max=row["effective_heat_at_max"],
        target=target,
    )

    if not decision.reachable:
        out["unreachable"] += 1
        out["journal"].append(
            {
                "id": row["id"],
                "heat_base_before": row["heat_base"],
                "effective_heat_before": row["effective_heat"],
                "effective_heat_at_max": row["effective_heat_at_max"],
                "outcome": "unreachable",
            }
        )
        return

    if not decision.changed:
        # effective_heat_before already >= target by the time this ran
        # (a concurrent write raised it since the scan) — nothing to do.
        out["already_above_target"] += 1
        return

    written = False
    if apply:
        written = apply_reheat(
            conn, row["id"], row["heat_base"], decision.new_heat_base
        )
    if apply and not written:
        out["skipped_race"] += 1
        return

    out["reheated"] += 1
    out["journal"].append(
        {
            "id": row["id"],
            "heat_base_before": row["heat_base"],
            "heat_base_after": decision.new_heat_base,
            "effective_heat_before": row["effective_heat"],
            "outcome": "reheated",
        }
    )


async def run_memory_reheat_pass(
    store: Any,
    *,
    apply: bool = False,
    target: float = DEFAULT_REHEAT_TARGET,
    limit: int = DEFAULT_REHEAT_SCAN_LIMIT,
) -> dict[str, Any]:
    """Raise ``heat_base`` for every active deliberate memory below ``target``.

    source: ADR-0368"""

    out: dict[str, Any] = {
        "scanned_rows": 0,
        "reheated": 0,
        "unreachable": 0,
        "already_above_target": 0,
        "skipped_race": 0,
        "journal": [],
        "status": "ok",
        "target": target,
    }
    try:
        with store.batch_pool.connection() as conn:
            rows = list_deliberate_below_target(conn, target, limit)
            out["scanned_rows"] = len(rows)
            for row in rows:
                _process_row(conn, row, target=target, apply=apply, out=out)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("memory_reheat_pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out


__all__ = ["DEFAULT_REHEAT_SCAN_LIMIT", "run_memory_reheat_pass"]
