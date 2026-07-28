"""Deliberate-heat recalibration pass: one-shot raise of ``heat_base`` for
active deliberate memories below the measured retrieval cliff (I6-D5,
INC6.6).

Composition root — wires ``core.memory_reheat`` (pure per-row decision)
to infrastructure (``pg_store_memory_reheat``'s scan-and-probe query and
CAS-guarded write). Mirrors ``memory_dedup_exact_pass.py``'s split (I6-D1
precedent): pure decision in core, I/O in infrastructure, wiring here.

One-shot campaign pass, not wired into ``consolidate``: I6-D5 explicitly
scopes this as a single recalibration with a J+30 re-measurement, not a
recurring maintenance job — whether periodic re-heat is needed is an open
question for the user once the J+30 data exists (design doc §"Questions
ouvertes" #4). Invoked by ``scripts/memory_reheat.py``.
"""

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

    Pre-condition:  ``store`` exposes ``batch_pool``
                    (``psycopg_pool.ConnectionPool``), matching
                    ``memory_dedup_exact_pass``/``memory_domain_backfill_
                    pass``'s convention for maintenance sweeps.
    Post-condition: for every active deliberate memory (source NOT IN the
                    auto-capture/mechanical set, ``NOT is_stale`` —
                    ``pg_store_memory_reheat.list_deliberate_below_
                    target``'s exact scope) whose ``effective_heat`` <
                    ``target`` at scan time: if
                    ``core.memory_reheat.compute_reheat_target`` decides
                    the row is reachable and needs a raise,
                    ``heat_base`` is CAS-written to the computed value IFF
                    ``apply`` is True (``reheated`` count + journal entry
                    with before/after); if the row cannot reach ``target``
                    even at ``heat_base=1.0`` (a genuine consolidation-
                    stage ceiling), it is left untouched and counted in
                    ``unreachable`` (also journaled, honestly, per §8 —
                    the campaign does not fabricate reaching a target it
                    cannot reach). ``apply=False`` performs the identical
                    scan and per-row decision without writing (dry run) —
                    ``reheated``/``unreachable``/journal are identical
                    either way, so a caller can diff dry-run vs. applied
                    output to confirm 1:1 correspondence (mirrors
                    ``memory_dedup_exact_pass``'s dry-run contract). A
                    concurrent write that changes a row's ``heat_base``
                    between scan and write is counted in
                    ``skipped_race`` and excluded from ``reheated`` (never
                    silently dropped — logged for the caller to re-run).
                    No row's ``heat_base`` is ever lowered
                    (``core.memory_reheat.compute_reheat_target``'s
                    ``max(heat_base_before, needed)`` floor) — the
                    invariant every test in this campaign checks.
    """

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
