"""Decay cycle — entity heat decay only.

Memory heat decay is **not** computed here. It is computed lazily at
read time by the ``effective_heat()`` PL/pgSQL function
(``mcp_server/infrastructure/pg_schema.py``), which applies the
stage-adjusted Ebbinghaus law and the consolidation-dependent
permastore floor server-side. This module retained an eager, per-row
Python decay path (including an alternative ACT-R base-level model)
until the A3 migration moved memory decay to the SQL side; both were
removed as dead code (zero production callers since that migration —
see issue #346) rather than kept as inert reference implementations,
per coding-standards.md §9 ("if it's built, it must be called").
History: `git show b9997157` (the migration commit) and
`docs/program/phase-3-a3-migration-design.md` §6 ("Decay cycle
post-A3 — DELETE") record the decision and its rationale.

What remains is **entity** heat decay: entities are not part of the
A3 lazy-heat migration (they retain an eager ``heat`` column), so they
still decay via a simple exponential law, applied per consolidation
pass by ``mcp_server/handlers/consolidation/decay.py``.

Naming note — do not confuse with ``ADAPTIVE_DECAY``: the
``ADAPTIVE_DECAY`` mechanism reported in the LoCoMo v3 ablation table
(``benchmarks/results/ablation/locomo_v3/summary.csv``) is an adaptive
*decay rate* on the memory-heat Ebbinghaus path — it lives in
``mcp_server/core/thermodynamics.py`` (``compute_decay``'s
``Mechanism.ADAPTIVE_DECAY`` gate), ``mcp_server/core/pg_recall.py``,
and is configured by ``ADAPTIVE_DECAY_ENABLED`` /
``ADAPTIVE_DECAY_MIN_RATE`` / ``ADAPTIVE_DECAY_MAX_RATE`` in
``mcp_server/infrastructure/memory_config.py``. It has never lived in
this module and is unrelated to entity decay or to the ACT-R model
that used to live here.

Pure business logic — receives entity data, returns updated heat values.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Minimum heat change worth persisting as an update.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_HEAT_DELTA: float = 0.001


def _parse_datetime(value) -> datetime | None:
    """Parse a datetime from either a string or native datetime object.

    psycopg3 returns native datetime objects from TIMESTAMPTZ columns,
    while some code paths pass ISO strings. Handle both.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _parse_hours_since_access(record: dict, now: datetime) -> float | None:
    """Parse hours since last access from an entity record.

    Fallback chain: last_accessed → ingested_at → created_at. Entities
    do not currently carry ingested_at, so this falls through to
    created_at for them, but the same fallback order is used so entity
    and memory records can share a parsing convention if that changes.
    """
    last_accessed = (
        record.get("last_accessed")
        or record.get("ingested_at")
        or record.get("created_at", "")
    )
    last_dt = _parse_datetime(last_accessed)
    if last_dt is None:
        return None
    hours = (now - last_dt).total_seconds() / 3600.0
    return hours if hours > 0 else None


def compute_entity_decay(
    entities: list[dict],
    now: datetime | None = None,
    *,
    decay_factor: float = 0.98,
    cold_threshold: float = 0.05,
) -> list[tuple[int, float]]:
    """Compute new heat values for entities.

    Entities use exponential decay (simpler — no access history tracked).
    Returns list of (entity_id, new_heat) tuples.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    updates: list[tuple[int, float]] = []
    for entity in entities:
        current_heat = entity.get("heat", 0.0)
        if current_heat < cold_threshold:
            continue
        hours = _parse_hours_since_access(entity, now)
        if hours is None:
            continue
        new_heat = current_heat * (decay_factor**hours)
        if abs(new_heat - current_heat) > _MIN_HEAT_DELTA:
            updates.append((entity["id"], round(new_heat, 6)))

    return updates
