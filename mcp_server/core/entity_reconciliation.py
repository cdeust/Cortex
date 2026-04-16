"""Entity reconciliation — keep memory_entities coverage high.

Curie's I4 audit (docs/invariants/cortex-invariants.md §I4 and
docs/program/phase-0.4.5-backfill-design.md) found two coverage defects:

1. A one-time undercoverage defect requiring a full backfill
   (`scripts/phase_0_4_5_backfill.sql`).
2. An ongoing "retroactive-entity-orphans" leak: when
   `persist_entities` creates an entity from memory M1 at time t1, no
   code links that entity's name to older memories M0 whose content
   textually contains the same name.

This module builds the *windowed* maintenance query that closes the
ongoing leak after the one-shot backfill lands. Run it on the
consolidate schedule (daily). Windowing keeps runtime proportional to
recent activity, not to store size.

Window semantics (both conditions AND'd, NOT OR'd):
  - memory is young enough to still be a likely target of new-entity
    linkage (default 7 days — consistent with LABILE and EARLY_LTP
    cascade stages, pg_schema.py:748-752)
  - entity is young enough that it was possibly introduced after the
    memory existed (default 24 hours — captures the write path's
    entity-creation-after-memory-creation case, but bounds the work).

Pure business logic. The SQL is returned to a handler / store adapter
that runs it. This module has no PostgreSQL driver dependency.

References:
  - Clean Architecture (Martin 2017) Ch. 20: the SQL is a policy the
    core owns; execution is an I/O concern of the store.
  - cortex-invariants.md I4 and I9.
"""

from __future__ import annotations

# ── Defaults ──────────────────────────────────────────────────────────────
#
# Source: chosen to be no larger than the cascade's LABILE+EARLY_LTP
# window so the reconcile job bounds work to memories that are still
# capable of being re-tagged during consolidation. See
# pg_schema.py:748-752 (decay_memories alpha exponents) and Kandel (2001)
# on consolidation windows. 7 days matches the dominant stage transition
# timeline for episodic memories.

DEFAULT_MEMORY_AGE_DAYS = 7
DEFAULT_ENTITY_AGE_HOURS = 24
DEFAULT_MIN_NAME_LENGTH = 4  # Option A — Curie audit, drops 117 junk entities


# ── SQL templates ─────────────────────────────────────────────────────────
#
# Both queries embed the same trigram-accelerated join shape proven in
# `scripts/phase_0_4_5_backfill.sql`. The windowed version additionally
# constrains `m.created_at` and `e.created_at`, so the planner's
# candidate-memory set is small enough to not require the session-scoped
# `enable_seqscan = off` trick that the full backfill uses.

_RECONCILE_SQL = """
INSERT INTO memory_entities (memory_id, entity_id)
SELECT m.id, e.id
FROM   entities e
JOIN   memories m
  ON   m.content ILIKE '%' || e.name || '%'
WHERE  length(e.name) >= %s
  AND  NOT e.archived
  AND  m.created_at > NOW() - make_interval(days => %s)
  AND  e.created_at > NOW() - make_interval(hours => %s)
ON CONFLICT (memory_id, entity_id) DO NOTHING
"""

_COUNT_ELIGIBLE_SQL = """
SELECT COUNT(*)
FROM   entities e
JOIN   memories m
  ON   m.content ILIKE '%' || e.name || '%'
WHERE  length(e.name) >= %s
  AND  NOT e.archived
  AND  m.created_at > NOW() - make_interval(days => %s)
  AND  e.created_at > NOW() - make_interval(hours => %s)
"""


def build_reconciliation_sql(
    memory_age_days: int = DEFAULT_MEMORY_AGE_DAYS,
    entity_age_hours: int = DEFAULT_ENTITY_AGE_HOURS,
    min_name_length: int = DEFAULT_MIN_NAME_LENGTH,
) -> tuple[str, tuple[int, int, int]]:
    """Return (SQL, params) for the windowed memory_entities reconciliation.

    Preconditions:
      - memory_age_days >= 1
      - entity_age_hours >= 1
      - min_name_length >= 1  (2 is minimum useful — pg_trgm needs 3-gram)

    Postconditions:
      - Returned SQL is an idempotent INSERT ... ON CONFLICT DO NOTHING.
      - Params tuple order matches the %s placeholders, left-to-right:
        (min_name_length, memory_age_days, entity_age_hours).
      - Query is windowed: planner can use idx_memories_created_at and
        idx_entities (no created_at index yet — see design doc §5 risks)
        to bound candidate rows before the trigram probe.

    Invariants:
      - The SQL never shrinks memory_entities (monotone adds only).
      - ON CONFLICT makes the query safe to run concurrently with
        write-path `persist_entities` and with the one-shot backfill.

    Args:
        memory_age_days: include memories created within this many days.
        entity_age_hours: include entities created within this many hours.
        min_name_length: drop short junk entity names (Option A policy).

    Returns:
        (sql_string, params_tuple). Pass both to psycopg.execute() —
        the SQL contains literal `%` characters (in the ILIKE patterns
        '%' || e.name || '%') which are safe only when the caller uses
        psycopg's parameter binding (`cursor.execute(sql, params)`),
        NOT string formatting (`cursor.execute(sql % params)`).
    """
    if memory_age_days < 1:
        raise ValueError(f"memory_age_days must be >= 1, got {memory_age_days}")
    if entity_age_hours < 1:
        raise ValueError(f"entity_age_hours must be >= 1, got {entity_age_hours}")
    if min_name_length < 1:
        raise ValueError(f"min_name_length must be >= 1, got {min_name_length}")

    params = (min_name_length, memory_age_days, entity_age_hours)
    return _RECONCILE_SQL, params


def build_count_eligible_sql(
    memory_age_days: int = DEFAULT_MEMORY_AGE_DAYS,
    entity_age_hours: int = DEFAULT_ENTITY_AGE_HOURS,
    min_name_length: int = DEFAULT_MIN_NAME_LENGTH,
) -> tuple[str, tuple[int, int, int]]:
    """Return (SQL, params) for counting eligible pairs in the window.

    Preconditions: same as build_reconciliation_sql.

    Postconditions:
      - Returned SQL selects a single BIGINT (the eligible-pair count).
      - Used to compute the "leak ratio" (see reconcile_leak_ratio()):
        if (inserted / eligible) > 0.01 then the write path is leaking.

    This is a read-only query; callers use it before running the
    reconciliation to compute the window's expected cardinality.
    """
    if memory_age_days < 1:
        raise ValueError(f"memory_age_days must be >= 1, got {memory_age_days}")
    if entity_age_hours < 1:
        raise ValueError(f"entity_age_hours must be >= 1, got {entity_age_hours}")
    if min_name_length < 1:
        raise ValueError(f"min_name_length must be >= 1, got {min_name_length}")

    params = (min_name_length, memory_age_days, entity_age_hours)
    return _COUNT_ELIGIBLE_SQL, params


def reconcile_leak_ratio(
    reconciled_pairs: int,
    eligible_pairs: int,
) -> float:
    """Compute the leak ratio for the reconcile job.

    Preconditions:
      - reconciled_pairs >= 0
      - eligible_pairs >= 0
      - reconciled_pairs <= eligible_pairs  (cannot insert more than the
        window contains; violation indicates a counting bug)

    Postconditions:
      - Returns a float in [0.0, 1.0].
      - If eligible_pairs == 0, returns 0.0 (no work → no leak).

    The ratio is: reconciled / eligible. A value above 0.01 (1%) means
    the write path is leaking — the ongoing I9 guarantee is not holding.
    Callers (handlers/consolidate.py) emit a WARN log above that
    threshold.

    Rationale for the 1% threshold: on a healthy system, the write path
    catches entities present at memory-write time, and reconcile catches
    only the retroactive-orphan case (new entity → older memory). On a
    66K store with <100 new entities/day and <1K new memories/day, the
    retroactive set is bounded; 1% of the 7d × 24h window's eligible
    pairs is an empirical upper bound for that case. Exceeding it is a
    signal, not a proof — a confirmation test needs RCA per Move 4.
    """
    if reconciled_pairs < 0:
        raise ValueError(f"reconciled_pairs must be >= 0, got {reconciled_pairs}")
    if eligible_pairs < 0:
        raise ValueError(f"eligible_pairs must be >= 0, got {eligible_pairs}")
    if reconciled_pairs > eligible_pairs:
        raise ValueError(
            f"reconciled_pairs ({reconciled_pairs}) > eligible_pairs "
            f"({eligible_pairs}) — counting bug"
        )

    if eligible_pairs == 0:
        return 0.0
    return reconciled_pairs / eligible_pairs


# ── Leak threshold constant ───────────────────────────────────────────────
#
# Source: empirical upper bound for the retroactive-entity-orphan rate on
# the darval 66K store (see design doc §6). Above this, the write path is
# demonstrably leaking. Below this, reconcile is serving its intended
# maintenance role. Not a magic number — it's the contract boundary
# between "working as designed" and "investigate now".

LEAK_WARNING_THRESHOLD = 0.01


def exceeds_leak_threshold(ratio: float) -> bool:
    """True if the leak ratio warrants a WARN log to operators.

    Preconditions: 0.0 <= ratio <= 1.0.
    Postconditions: returns (ratio > LEAK_WARNING_THRESHOLD).
    """
    if ratio < 0.0 or ratio > 1.0:
        raise ValueError(f"ratio must be in [0.0, 1.0], got {ratio}")
    return ratio > LEAK_WARNING_THRESHOLD
