"""Memory query mixin for PgMemoryStore: filtered reads, time-window queries.

Streaming/chunked reads live in the sibling ``pg_store_query_stream``
module and entity co-access JOIN queries in ``pg_store_co_access``
(both split out by issue #407: this file was 401 lines over the
300-line §4.1 cap).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgQueryMixin(PgStoreHost):
    """Read-only memory queries on PostgreSQL."""

    def get_memories_for_domain(
        self,
        domain: str,
        min_heat: float = 0.05,
        limit: int = 50,
        heads_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Shared primitive with mixed callers. heads_only routes the read
        through the current_memories view (supersession chain heads only):
        content-serving callers (recall_hierarchical, drill_down) pass True;
        maintenance callers (validate_memory) keep False to see full chains.
        """
        src = "current_memories" if heads_only else "memories"
        rows = self._execute(
            f"SELECT * FROM {src} WHERE (domain = %s OR is_global = TRUE) "  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            "AND heat_base >= %s ORDER BY heat_base DESC LIMIT %s",
            (domain, min_heat, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_for_directory(
        self, directory: str, min_heat: float = 0.05
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE (directory_context = %s OR is_global = TRUE) "
            "AND heat_base >= %s ORDER BY heat_base DESC",
            (directory, min_heat),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_hot_memories(
        self,
        min_heat: float = 0.7,
        limit: int = 20,
        include_benchmarks: bool = False,
        heads_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Shared primitive with mixed callers. heads_only routes the read
        through the current_memories view (supersession chain heads only):
        content-serving callers (drill_down, write-gate struct_nov) pass
        True; maintenance/stats callers keep False.
        """
        src = "current_memories" if heads_only else "memories"
        bench_filter = (
            "" if include_benchmarks else "AND NOT coalesce(is_benchmark, FALSE) "
        )
        if limit > 0:
            rows = self._execute(
                f"SELECT * FROM {src} WHERE heat_base >= %s {bench_filter}"  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                "ORDER BY heat_base DESC LIMIT %s",
                (min_heat, limit),
            ).fetchall()
        else:
            rows = self._execute(
                f"SELECT * FROM {src} WHERE heat_base >= %s {bench_filter}"  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                "ORDER BY heat_base DESC",
                (min_heat,),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT id, heat_base, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("embedding") is not None:
                d["embedding"] = self._vector_to_bytes(d["embedding"])
            results.append(d)
        return results

    def get_all_memories_for_validation(
        self,
        limit: int = 1000,
        *,
        after_id: int = 0,
        include_stale: bool = False,
    ) -> list[dict[str, Any]]:
        """Page through memories for validation, ``id`` order (I6-D6).

        ``after_id`` is a cursor: pass the max ``id`` seen in the previous
        page to continue. Ordering is by ``id ASC`` (not ``last_accessed``)
        specifically so the cursor is stable across calls — last_accessed
        can change between pages if a validation pass itself touches rows.
        ``include_stale`` defaults False (unchanged behavior for existing
        callers — assess_coverage, change_impact); validate_memory passes
        True so a provenance re-check can rehabilitate (de-stale) a
        memory whose references all resolve again.
        """
        rows = self._execute(
            "SELECT * FROM memories WHERE id > %s AND (NOT is_stale OR %s) "
            "ORDER BY id ASC LIMIT %s",
            (after_id, include_stale, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_created_after(
        self, iso_timestamp: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE created_at >= %s "
            "ORDER BY created_at ASC LIMIT %s",
            (iso_timestamp, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_in_time_window(
        self, center_time: str, window_minutes: int
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE "
            "ABS(EXTRACT(EPOCH FROM (created_at - %s::timestamptz))) / 60 <= %s",
            (center_time, window_minutes),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_for_decay(self) -> list[dict[str, Any]]:
        rows = self._execute("SELECT * FROM memories WHERE NOT is_stale").fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_by_tag(self, tag: str, limit: int = 20) -> list[dict[str, Any]]:
        """Most-recent-first memories carrying ``tag``.

        Replaces full-table scans that filtered by tag in Python
        (bounded-I/O audit 2026-06-09). Recency correctness is guaranteed
        by the ORDER BY; ``limit`` only bounds the scan — callers that
        skip dead entries (e.g. graph memos whose path was deleted) get
        ``limit`` candidates of headroom.
        """
        rows = self._execute(
            "SELECT * FROM memories "
            "WHERE tags @> %s::jsonb AND NOT is_stale "
            "ORDER BY created_at DESC LIMIT %s",
            (json.dumps([tag]), limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def search_by_tag_vector(
        self,
        query_embedding: bytes | None,
        tag: str,
        domain: str | None = None,
        min_heat: float = 0.01,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Vector search filtered by tag. Returns scored memories.

        ENGRAM (arxiv 2511.12960): per-type retrieval pools guarantee
        typed memories (preference, instruction) are not drowned out.
        """

        emb = (
            np.frombuffer(query_embedding, dtype=np.float32)
            if query_embedding
            else None
        )
        # current_memories (both branches): typed pool hits are inserted at
        # rank 0 by the caller — a superseded instruction/preference served
        # here would outrank its own correction, so exclusion at the source
        # is the only safe placement.
        if emb is not None:
            rows = self._execute(
                "SELECT *, (1.0 - (embedding <=> %s))::REAL AS score "
                "FROM current_memories "
                "WHERE tags @> %s::jsonb AND heat_base >= %s AND NOT is_stale "
                "AND embedding IS NOT NULL "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY embedding <=> %s LIMIT %s",
                (emb, json.dumps([tag]), min_heat, domain, domain, emb, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT *, heat_base::REAL AS score "
                "FROM current_memories "
                "WHERE tags @> %s::jsonb AND heat_base >= %s AND NOT is_stale "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY heat_base DESC LIMIT %s",
                (json.dumps([tag]), min_heat, domain, domain, limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def delete_memories_by_tag(self, tag: str, domain: str | None = None) -> int:
        """Delete memories with the given tag, optionally scoped to a domain.

        precondition: tag is a non-empty string; domain is None or a non-empty string.
        postcondition: returns the number of rows removed; rows removed iff their
            tags JSONB contains [tag] AND (domain is None OR domain matches).
            domain=None preserves global-purge behavior for callers that
            actually want it (legacy contract). Caller is responsible for
            passing domain when scope matters (e.g. seed_project, which is
            per-repo by design — see issue #16).
        """
        if domain is None:
            cur = self._execute(
                "DELETE FROM memories WHERE tags @> %s::jsonb",
                (json.dumps([tag]),),
            )
        else:
            cur = self._execute(
                "DELETE FROM memories WHERE tags @> %s::jsonb AND domain = %s",
                (json.dumps([tag]), domain),
            )
        self._conn.commit()
        return cur.rowcount
