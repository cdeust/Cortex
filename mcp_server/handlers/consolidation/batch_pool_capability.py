"""Capability guard for the PostgreSQL-only batch connection pool.

Several consolidation passes need a long-running SQL connection
(``store.batch_pool``, a ``psycopg_pool.ConnectionPool``) to reach
Postgres-schema-qualified tables (``wiki.pages``, ``wiki.citations``, the
``memories`` write-class backfill, ...) that have no SQLite equivalent.
``SqliteMemoryStore`` has no ``batch_pool`` attribute at all, so an
unconditional ``store.batch_pool.connection()`` raised ``AttributeError``
on every SQLite install — indistinguishable, once caught, from a real
query failure. This turns the gap into a named, expected skip instead.

source: ADR-1089
"""

from __future__ import annotations

from typing import Any


def batch_pool_skip_reason(store: Any) -> str | None:
    """``None`` when ``store.batch_pool`` is usable; else the skip reason.

    Plain ``hasattr`` rather than a ``runtime_checkable`` Protocol: this
    guards one attribute, not a multi-member capability, and
    ``tests_py/handlers/consolidation/test_wiki_citation_seed_pass.py``
    already establishes ``hasattr(store, "batch_pool")`` as this
    capability's check.

    source: ADR-1089
    """
    if hasattr(store, "batch_pool"):
        return None
    return "store has no batch_pool (non-PostgreSQL backend)"
