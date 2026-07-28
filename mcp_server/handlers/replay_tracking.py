"""Handler: replay_tracking — shared per-event CLS-B hippocampal decay.

Every recall-family handler (recall, recall_hierarchical, navigate_memory,
drill_down) treats a memory surfacing in its results as a hippocampal replay
event (McClelland et al. 1995). Each such event should:

  1. bump access_count / replay_count (existing behaviour), and
  2. decrement hippocampal_dependency by exactly one C-HORSE transfer delta
     (Ketz et al. 2023, eLife 12:e77185) — the CLS-B producer this module
     wires into the shared replay path so it fires identically at all four
     call sites instead of being re-derived per handler.

Policy (whether/how much to decay) lives here, in the handler layer.
Persistence (reading the post-increment row, writing the new dependency)
lives in the infra store methods this module calls — the store never decides
*when* to decay, only *how* to read/write a row.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.two_stage_transfer import update_hippocampal_dependency

logger = logging.getLogger(__name__)


def _float_or(value: Any, default: float) -> float:
    """``float(value)`` unless ``value`` is missing/None — never treats a
    legitimate 0.0 as missing (``x or default`` would, since 0.0 is falsy)."""
    return default if value is None else float(value)


def track_replay_event(memory_id: int, store: Any) -> None:
    """Record one hippocampal replay event for ``memory_id`` on ``store``.

    Precondition: ``memory_id`` identifies a memory that may or may not still
    exist at call time (best-effort — the memory can be deleted between
    enrichment and this call in a concurrent session).

    Postcondition: on success, access_count and replay_count are each
    incremented by 1. If ``Mechanism.TWO_STAGE_MODEL`` is not ablated,
    hippocampal_dependency is decreased by exactly the transfer delta for
    this single replay (``compute_transfer_delta`` — zero once replay_count
    is below the minimum-replays guard or dependency is already at/below the
    release threshold, so most single calls are a no-op past that point).
    When ablated, dependency is left untouched and only the counters advance
    (pre-existing behaviour, CLS-B producer disabled).

    FAILS_ON: transient store errors (connection drop, row already deleted).
    Replay tracking is best-effort telemetry for a background consolidation
    signal — it must never fail the parent recall/navigate/drill_down call,
    so all store errors are swallowed here (matches the pre-existing
    try/except at each of the four call sites this module replaces).
    """
    try:
        store.update_memory_access(memory_id)
        stats = store.increment_replay_count(memory_id)
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Replay tracking failed for memory %s", memory_id, exc_info=True)
        return

    if not stats or is_mechanism_disabled(Mechanism.TWO_STAGE_MODEL):
        return

    current_dependency = _float_or(stats.get("hippocampal_dependency"), 1.0)
    new_dependency = update_hippocampal_dependency(
        current_dependency,
        int(_float_or(stats.get("replay_count"), 0.0)),
        _float_or(stats.get("schema_match_score"), 0.0),
        _float_or(stats.get("importance"), 0.5),
    )
    if new_dependency == current_dependency:
        return

    try:
        store.update_memory_hippocampal_dependency(memory_id, new_dependency)
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug(
            "Hippocampal dependency write failed for memory %s",
            memory_id,
            exc_info=True,
        )
