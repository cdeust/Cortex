"""PostgreSQL + pgvector memory store — composition root.

source: ADR-0538"""

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
from mcp_server.infrastructure.pg_store_signals import PgSignalsMixin
from mcp_server.infrastructure.pg_store_checkpoint import PgCheckpointMixin
from mcp_server.infrastructure.pg_store_prospective import PgProspectiveMixin
from mcp_server.infrastructure.pg_store_procedural import PgProceduralMixin
from mcp_server.infrastructure.pg_store_archive import PgArchiveMixin
from mcp_server.infrastructure.pg_store_engram import PgEngramMixin
from mcp_server.infrastructure.pg_store_cortical_schema import PgCorticalSchemaMixin
from mcp_server.infrastructure.pg_store_entities import PgEntityMixin
from mcp_server.infrastructure.pg_store_entity_merge import PgEntityMergeMixin
from mcp_server.infrastructure.pg_store_queries import PgQueryMixin
from mcp_server.infrastructure.pg_store_query_stream import PgQueryStreamMixin
from mcp_server.infrastructure.pg_store_co_access import PgCoAccessMixin
from mcp_server.infrastructure.pg_store_receipts import PgReceiptsMixin
from mcp_server.infrastructure.pg_store_relationships import PgRelationshipMixin
from mcp_server.infrastructure.pg_store_rules import PgRuleMixin
from mcp_server.infrastructure.pg_store_stats import PgStatsMixin
from mcp_server.infrastructure.pg_store_consolidation_stage import (
    PgConsolidationStageMixin,
)
from mcp_server.infrastructure.pg_store_cls import PgClsMixin

logger = logging.getLogger(__name__)

# source: ADR-0538
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
    PgSignalsMixin,
    PgEntityMixin,
    PgEntityMergeMixin,
    PgRelationshipMixin,
    PgQueryMixin,
    PgQueryStreamMixin,
    PgCoAccessMixin,
    PgReceiptsMixin,
    PgRuleMixin,
    PgStatsMixin,
    PgConsolidationStageMixin,
    PgClsMixin,
    PgCheckpointMixin,
    PgProspectiveMixin,
    PgProceduralMixin,
    PgArchiveMixin,
    PgEngramMixin,
    PgCorticalSchemaMixin,
):
    """PostgreSQL + pgvector storage engine for Cortex memory system."""

    def __init__(self, database_url: str | None = None) -> None:
        self._url = database_url or _get_database_url()
        self._conn = self._create_connection()
        self._init_schema()
        # source: ADR-0538
        self._deallocate_all()
        register_vector(self._conn)
        # source: ADR-0538
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
