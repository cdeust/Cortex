"""SQLite recall: client-side WRRF fusion of the recall signals.

The PostgreSQL store fuses inside ``recall_memories()`` (pg_schema.py); here
the vector, FTS5, heat and recency signals are rank-fused in Python, then
agent and trust adjustments apply and the best ``max_results * 3`` ids are
read back. Sets of ids are bound as one JSON array (``json_each``), so a tie
group of any size never meets the bind-variable limit (ADR-1109).

source: ADR-0616
source: ADR-1109
"""

from __future__ import annotations

import heapq
import json
from typing import Any

from mcp_server.infrastructure.sqlite_store_recall_signals import (
    IDS_IN,
    SqliteRecallSignalsMixin,
    json_ids,
)


def _decode_tags(raw: Any) -> list:
    """Deserialize a SQLite ``tags`` TEXT column into a list.

    source: ADR-0616"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return raw or []


def _visible(
    row: Any, min_heat: float, domain: str | None, directory: str | None
) -> bool:
    """Whether a ranked row passes the recall filters.

    source: ADR-0616"""
    if row["heat_base"] < min_heat or row["is_stale"]:
        return False
    is_global = bool(row.get("is_global", 0))
    if domain and row["domain"] != domain and not is_global:
        return False
    return not (directory and row["directory_context"] != directory and not is_global)


def _result(mid: int, row: Any, score: float) -> dict[str, Any]:
    """One recall result in the store-neutral shape.

    source: ADR-0616"""
    return {
        "memory_id": mid,
        "content": row["content"],
        "score": score,
        "heat": row["heat_base"],
        "domain": row["domain"],
        "created_at": row["created_at"],
        "store_type": row["store_type"],
        "tags": _decode_tags(row["tags"]),
        "importance": row["importance"],
        "surprise_score": row["surprise_score"],
        # source: ADR-0616
        "capture_origin": row["capture_origin"],
    }


class SqliteRecallMixin(SqliteRecallSignalsMixin):
    """``recall_memories`` for SqliteMemoryStore."""

    def recall_memories(
        self,
        query_text: str,
        query_embedding: bytes | None,
        intent: str = "general",
        domain: str | None = None,
        directory: str | None = None,
        agent_topic: str | None = None,
        min_heat: float = 0.05,
        max_results: int = 10,
        wrrf_k: int = 60,
        weights: dict[str, float] | None = None,
        include_globals: bool = True,
        trusted_origins: tuple[str, ...] = (),
        untrusted_factor: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Client-side WRRF fusion: vector + FTS5 + heat + recency.

        source: ADR-0616"""
        w = weights or {}
        w_vector = w.get("vector", 1.0)
        pool = max_results * 10
        where = self._build_filter(min_heat, domain, directory)
        scores: dict[int, float] = {}
        self._signal_vector(scores, query_embedding, w_vector, wrrf_k, pool)
        self._signal_fts(scores, query_text, w.get("fts", 0.5), wrrf_k, pool)
        self._signal_heat(scores, w.get("heat", 0.3), wrrf_k, pool, where)
        self._signal_recency(scores, w.get("recency", 0.0), wrrf_k, pool, where)
        self._apply_agent_boost(scores, agent_topic, w_vector, wrrf_k)
        self._apply_trust_factor(scores, trusted_origins, untrusted_factor)
        if not scores:
            return []
        return self._fetch_ranked_results(
            scores, max_results, min_heat, domain, directory
        )

    def _apply_agent_boost(
        self,
        scores: dict[int, float],
        agent_topic: str | None,
        w_vector: float,
        wrrf_k: int,
    ) -> None:
        """source: ADR-0616"""
        if not agent_topic or not scores:
            return
        boost = 0.3 * (w_vector / wrrf_k)
        rows = self._conn.execute(
            f"SELECT id FROM memories WHERE id {IDS_IN} AND agent_context = ?",  # noqa: S608 — IDS_IN is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            (json_ids(scores), agent_topic),
        ).fetchall()
        for r in rows:
            scores[r["id"]] += boost

    def _apply_trust_factor(
        self,
        scores: dict[int, float],
        trusted_origins: tuple[str, ...],
        untrusted_factor: float,
    ) -> None:
        """Multiplicative, not additive: an additive penalty cannot demote a
        passage that wins on similarity.

        source: ADR-0616"""
        if not scores or untrusted_factor == 1.0:
            return
        rows = self._conn.execute(
            f"SELECT id, capture_origin FROM memories WHERE id {IDS_IN}",  # noqa: S608 — IDS_IN is an in-code literal; the ids are one bound parameter (docs/ASSURANCE-CASE.md §5)
            (json_ids(scores),),
        ).fetchall()
        trusted = set(trusted_origins)
        for r in rows:
            # source: ADR-0616
            if r["capture_origin"] not in trusted:
                scores[r["id"]] *= untrusted_factor

    def _ranked_ids(self, scores: dict[int, float], top: int) -> list[int]:
        """The ``top`` best ids in score order; exact ties go to the newer memory.

        Ids above the ``top``-th score are sorted here; the group tied at that
        score fills the remaining places newest first in SQL, so a tie group
        holding every memory is never read back whole (ADR-1109).

        source: ADR-1106"""
        ids = list(scores)
        if len(ids) <= top:
            return self._newest_first_by_score(ids, scores)
        cut = heapq.nlargest(top, scores.values())[-1]
        above = [i for i in ids if scores[i] > cut]
        tied = [i for i in ids if scores[i] == cut]
        return self._newest_first_by_score(above, scores) + self._newest_first(
            tied, top - len(above)
        )

    def _newest_first_by_score(
        self, ids: list[int], scores: dict[int, float]
    ) -> list[int]:
        """``ids`` by score, then ``created_at``, then id, all descending.

        source: ADR-1106"""
        created = {
            r["id"]: r["created_at"]
            for r in self._conn.execute(
                f"SELECT id, created_at FROM memories WHERE id {IDS_IN}",  # noqa: S608 — IDS_IN is an in-code literal; the ids are one bound parameter (docs/ASSURANCE-CASE.md §5)
                (json_ids(ids),),
            ).fetchall()
        }
        return sorted(ids, key=lambda i: (scores[i], created[i], i), reverse=True)

    def _newest_first(self, ids: list[int], limit: int) -> list[int]:
        """The ``limit`` newest of ``ids`` (``created_at DESC, id DESC``).

        source: ADR-1106"""
        return [
            r["id"]
            for r in self._conn.execute(
                f"SELECT id FROM memories WHERE id {IDS_IN} "  # noqa: S608 — IDS_IN is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (json_ids(ids), limit),
            ).fetchall()
        ]

    def _fetch_ranked_results(
        self,
        scores: dict[int, float],
        max_results: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> list[dict[str, Any]]:
        """source: ADR-0616"""
        top_ids = self._ranked_ids(scores, max_results * 3)
        # source: ADR-0616
        row_map = {
            r["id"]: r
            for r in self._conn.execute(
                f"SELECT * FROM current_memories WHERE id {IDS_IN}",  # noqa: S608 — IDS_IN is an in-code literal; the ids are one bound parameter (docs/ASSURANCE-CASE.md §5)
                (json_ids(top_ids),),
            ).fetchall()
        }
        return [
            _result(mid, row_map[mid], scores[mid])
            for mid in top_ids
            if mid in row_map and _visible(row_map[mid], min_heat, domain, directory)
        ]
