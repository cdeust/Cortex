"""Entity reconciliation — keep memory_entities coverage high.

source: ADR-0178"""

from __future__ import annotations

# source: ADR-0178


DEFAULT_MEMORY_AGE_DAYS = 7
DEFAULT_ENTITY_AGE_HOURS = 24
DEFAULT_MIN_NAME_LENGTH = 4  # Option A — Curie audit, drops 117 junk entities


# source: ADR-0178


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

    source: ADR-0178

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


def reconcile_leak_ratio(
    reconciled_pairs: int,
    eligible_pairs: int,
) -> float:
    """Compute the leak ratio for the reconcile job.

    source: ADR-0178

    Postconditions:
      - Returns a float in [0.0, 1.0].
      - If eligible_pairs == 0, returns 0.0 (no work → no leak).

    The ratio is: reconciled / eligible. A value above 0.01 (1%) means
    the write path is leaking — the ongoing I9 guarantee is not holding.
    Callers (handlers/consolidate.py) emit a WARN log above that
    threshold.

    source: ADR-0178"""
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


# source: ADR-0178


LEAK_WARNING_THRESHOLD = 0.01


def exceeds_leak_threshold(ratio: float) -> bool:
    """True if the leak ratio warrants a WARN log to operators.

    Preconditions: 0.0 <= ratio <= 1.0.
    Postconditions: returns (ratio > LEAK_WARNING_THRESHOLD).
    """
    if ratio < 0.0 or ratio > 1.0:
        raise ValueError(f"ratio must be in [0.0, 1.0], got {ratio}")
    return ratio > LEAK_WARNING_THRESHOLD
