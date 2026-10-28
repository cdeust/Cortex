"""PostgreSQL half of hard forget: one transaction over every copy.

source: ADR-1111"""

from __future__ import annotations

from mcp_server.infrastructure.memory_erasure import (
    ErasureReport,
    erase_derived_rows,
    erase_entities,
    erase_pages,
)
from mcp_server.infrastructure.pg_store_host import PgStoreHost
from mcp_server.shared.wiki_pointer import is_pointer_source


class PgErasureMixin(PgStoreHost):
    def erase_memory(self, memory_id: int) -> ErasureReport:
        """Delete the memory and every row holding a copy of its text.

        Raises (and erases nothing) if any statement fails."""
        report = ErasureReport()
        with self.acquire_interactive() as conn, conn.transaction():
            row = conn.execute(
                "SELECT source FROM memories WHERE id = %s FOR UPDATE", (memory_id,)
            ).fetchone()
            if row is None:
                return report
            erase_derived_rows(conn, memory_id, report)
            if not is_pointer_source(row["source"]):
                erase_pages(conn, memory_id, report)
            erase_entities(conn, memory_id, report)
            conn.execute(
                "UPDATE wiki.concepts SET grounding_memory_ids = "
                "array_remove(grounding_memory_ids, %s) "
                "WHERE %s = ANY(grounding_memory_ids)",
                (memory_id, memory_id),
            )
            cur = conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
            report.deleted = cur.rowcount > 0
        # PostgreSQL keeps dead tuples until VACUUM reclaims them; the text is
        # unreachable through SQL from here (ADR-1111, limits).
        report.fts_method = "generated-column"
        return report
