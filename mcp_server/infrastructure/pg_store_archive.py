"""Memory-archive mixin for PgMemoryStore.

Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — schema-mismatch archival is its own concern,
distinct from prospective/procedural/engram/cortical-schema storage.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgArchiveMixin(PgStoreHost):
    """Schema-mismatch memory archive on PostgreSQL."""

    def insert_archive(self, data: dict[str, Any]) -> int:
        emb = self._bytes_to_vector(data.get("embedding"))
        row = self._execute(
            "INSERT INTO memory_archives "
            "(original_memory_id, content, embedding, "
            "mismatch_score, archive_reason) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (
                data["original_memory_id"],
                data["content"],
                emb,
                data.get("mismatch_score", 0.0),
                data.get("archive_reason", ""),
            ),
        ).one()
        self._conn.commit()
        return row["id"]

    def get_archives_for_memory(self, memory_id: int) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memory_archives "
            "WHERE original_memory_id = %s ORDER BY archived_at DESC",
            (memory_id,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]
