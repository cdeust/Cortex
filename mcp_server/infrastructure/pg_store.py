"""PostgreSQL + pgvector memory store — composition root.

Single storage backend for all memory operations. Retrieval logic lives
in PL/pgSQL stored procedures. Benchmarks and production use the same
code path.

``PgMemoryStore`` is assembled from the ``Pg*Mixin`` classes below, each
implementing one concern (connection/pool lifecycle, DDL migration,
value serialization, the INSERT path, atomic supersession, heat
writers, memory-metadata writers, search/retrieval) — split out of a
single 1384-line file (over the 300-line §4.1 cap) along those
boundaries. This module is the thin facade: it owns only construction
(``__init__``) and teardown (``close``), plus re-exporting the
module-level DDL helpers (``compute_ddl_hash``, ``read_schema_hash``,
``_get_database_url``) that ``mcp_server.migrate`` — a standalone entry
point that must decide "is the DB current" without constructing a full
store — imports from this path.

Phase 5 connection pools (docs/program/phase-5-pool-admission-design.md):
    * ``_interactive_pool`` — hot-path tools (recall, remember, etc.)
    * ``_batch_pool`` — long-running writers (consolidate, wiki_pipeline)
    * ``_conn`` — persistent single connection kept for backward compat
      with 281 existing call sites. New code should use
      ``acquire_interactive()`` / ``acquire_batch()`` context managers.

Requires: psycopg[binary]>=3.1, psycopg_pool>=3.2, pgvector>=0.3
"""

from __future__ import annotations

import logging

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool

from mcp_server.infrastructure.pg_store_ddl import (
    PgDdlMixin,
    _get_database_url,
    compute_ddl_hash,
    read_schema_hash,
)
from mcp_server.infrastructure.pg_store_schema import PgSchemaMixin
from mcp_server.infrastructure.pg_store_serialize import PgSerializeMixin
from mcp_server.infrastructure.pg_store_write import PgWriteMixin
from mcp_server.infrastructure.pg_store_supersede import PgSupersedeMixin
from mcp_server.infrastructure.pg_store_heat import PgHeatMixin
from mcp_server.infrastructure.pg_store_memory_meta import PgMemoryMetaMixin
from mcp_server.infrastructure.pg_store_search import PgSearchMixin
from mcp_server.infrastructure.pg_store_auxiliary import PgAuxiliaryMixin
from mcp_server.infrastructure.pg_store_entities import PgEntityMixin
from mcp_server.infrastructure.pg_store_entity_merge import PgEntityMergeMixin
from mcp_server.infrastructure.pg_store_queries import PgQueryMixin
from mcp_server.infrastructure.pg_store_receipts import PgReceiptsMixin
from mcp_server.infrastructure.pg_store_relationships import PgRelationshipMixin
from mcp_server.infrastructure.pg_store_rules import PgRuleMixin
from mcp_server.infrastructure.pg_store_stats import PgStatsMixin

logger = logging.getLogger(__name__)

# Re-exported for external callers (mcp_server.migrate, tests) that import
# these module-level DDL helpers from this facade path — see module
# docstring. Single source of truth stays pg_store_ddl.py.
__all__ = [
    "PgMemoryStore",
    "compute_ddl_hash",
    "read_schema_hash",
]


class PgMemoryStore(
    PgSchemaMixin,
    PgDdlMixin,
    PgSerializeMixin,
    PgWriteMixin,
    PgSupersedeMixin,
    PgHeatMixin,
    PgMemoryMetaMixin,
    PgSearchMixin,
    PgEntityMixin,
    PgEntityMergeMixin,
    PgRelationshipMixin,
    PgQueryMixin,
    PgReceiptsMixin,
    PgRuleMixin,
    PgStatsMixin,
    PgAuxiliaryMixin,
):
    """PostgreSQL + pgvector storage engine for Cortex memory system."""

    def __init__(self, database_url: str | None = None) -> None:
        self._url = database_url or _get_database_url()
        self._conn = self._create_connection()
        self._init_schema()
        # Invalidate prepared statements after schema DDL — stored procedure
        # signatures may have changed, making cached plans stale.
        self._deallocate_all()
        register_vector(self._conn)
        # Phase 5 pools — lazy-constructed; opening on first acquire
        # avoids paying pool-open cost for short-lived usages (tests).
        self._interactive_pool: ConnectionPool[psycopg.Connection[DictRow]] | None = (
            None
        )
        self._batch_pool: ConnectionPool[psycopg.Connection[DictRow]] | None = None

    def close(self) -> None:
        if self._interactive_pool is not None:
            try:
                self._interactive_pool.close()
            except Exception as exc:  # noqa: BLE001 — teardown continues past a failed close
                logger.debug("interactive pool close failed: %s", exc)
            self._interactive_pool = None
        if self._batch_pool is not None:
            try:
                self._batch_pool.close()
            except Exception as exc:  # noqa: BLE001 — teardown continues past a failed close
                logger.debug("batch pool close failed: %s", exc)
            self._batch_pool = None
        self._conn.close()
