"""Search mixins for MemoryStore: FTS5 full-text and vector KNN search."""

from __future__ import annotations

import sqlite3


class MemorySearchMixin:
    """FTS5 and vector search operations.

    Requires _conn (sqlite3.Connection) and _has_vec (bool) on the host class.
    """

    _conn: sqlite3.Connection
    _has_vec: bool

    # ── FTS5 Search ────────────────────────────────────────────────────

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[int, float]]:
        """Full-text search. Returns (memory_id, bm25_score) pairs."""
        safe_query = query.replace('"', '""')
        try:
            rows = self._conn.execute(
                "SELECT rowid, bm25(memories_fts) as score "
                "FROM memories_fts WHERE memories_fts MATCH ? "
                "ORDER BY score LIMIT ?",
                (safe_query, limit),
            ).fetchall()
            return [(r["rowid"], abs(r["score"])) for r in rows]
        except sqlite3.OperationalError:
            return []

    # ── Vector Search ──────────────────────────────────────────────────

    def insert_vector(self, memory_id: int, embedding: bytes) -> None:
        if not self._has_vec:
            return
        self._conn.execute(
            "INSERT INTO memory_vectors(rowid, embedding) VALUES (?, ?)",
            (memory_id, embedding),
        )

    def delete_vector(self, memory_id: int) -> None:
        if not self._has_vec:
            return
        self._conn.execute("DELETE FROM memory_vectors WHERE rowid = ?", (memory_id,))

    def search_vectors(
        self,
        query_embedding: bytes,
        top_k: int = 10,
        min_heat: float = 0.0,
    ) -> list[tuple[int, float]]:
        """KNN vector search. Returns (memory_id, distance) pairs."""
        if not self._has_vec:
            return []
        try:
            rows = self._conn.execute(
                "SELECT v.rowid, v.distance FROM memory_vectors v "
                "JOIN memories m ON m.id = v.rowid "
                "WHERE v.embedding MATCH ? AND k = ? AND m.heat >= ? "
                "ORDER BY v.distance",
                (query_embedding, top_k, min_heat),
            ).fetchall()
            return [(r["rowid"], r["distance"]) for r in rows]
        except Exception:
            return []

    # ── Compression ────────────────────────────────────────────────────

    def update_memory_compression(
        self,
        memory_id: int,
        content: str,
        embedding: bytes | None,
        compression_level: int,
        original_content: str | None = None,
    ) -> None:
        """Update a memory's content and compression level."""
        if original_content is not None:
            self._conn.execute(
                "UPDATE memories SET content = ?, embedding = ?, "
                "compression_level = ?, compressed = 1, original_content = ? "
                "WHERE id = ?",
                (content, embedding, compression_level, original_content, memory_id),
            )
        else:
            self._conn.execute(
                "UPDATE memories SET content = ?, embedding = ?, "
                "compression_level = ?, compressed = 1 "
                "WHERE id = ?",
                (content, embedding, compression_level, memory_id),
            )
        self._update_fts_and_vector(memory_id, content, embedding)
        self._conn.commit()

    def _update_fts_and_vector(
        self, memory_id: int, content: str, embedding: bytes | None
    ) -> None:
        """Re-index FTS5 and vector table after content change."""
        self._conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        self._conn.execute(
            "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
            (memory_id, content),
        )
        if embedding and self._has_vec:
            try:
                self.delete_vector(memory_id)
            except Exception:
                pass
            self.insert_vector(memory_id, embedding)
