"""Shared PostgreSQL-only guard for batch_pool campaign scripts.

source: issue #636
"""

from __future__ import annotations

import sys


def require_postgres_store(store: object) -> None:
    """Exit the process if `store` has no `batch_pool` (SQLite-backed).

    memory_dedup_exact, memory_domain_backfill, memory_reheat,
    near_dup_calibrate, and backfill_write_class each drive their
    campaign directly off PostgreSQL's batch_pool; SQLite has no
    equivalent, and letting the campaign run anyway would silently no-op
    rather than report that it never ran.
    """
    if not hasattr(store, "batch_pool"):
        print(
            "This campaign requires a PostgreSQL-backed store (batch_pool); "
            "the SQLite backend has no equivalent table for it.",
            file=sys.stderr,
        )
        sys.exit(1)
