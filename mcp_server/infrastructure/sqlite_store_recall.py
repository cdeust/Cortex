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

import json
from typing import Any

from mcp_server.infrastructure.sqlite_store_recall_fill import (
    Adjustments,
    group_candidates,
)
from mcp_server.infrastructure.sqlite_store_recall_groups import (
    PendingGroup,
    finalize_groups,
)
from mcp_server.infrastructure.sqlite_store_recall_signals import (
    HEAT,
    IDS_IN,
    RECENCY,
    VEC,
    SqliteRecallSignalsMixin,
    json_ids,
)
from mcp_server.infrastructure.sqlite_store_search import FTS
from mcp_server.shared.tie_groups import TieGroup, ordered_sum

# source: ADR-1106 -- (heat_base DESC, id DESC) keeps the (heat_base) index
# plan; recency breaks ties newest first.
_HEAT_ORDER = "heat_base DESC, id DESC"
_AGE_ORDER = "created_at DESC, id DESC"


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
        filters = (min_heat, domain, directory)
        adj = Adjustments(
            agent_topic,
            0.3 * (w.get("vector", 1.0) / wrrf_k),
            tuple(trusted_origins),
            untrusted_factor,
        )
        contribs, pending = self._contributions(
            query_text, query_embedding, w, (wrrf_k, max_results * 10), filters
        )
        if not contribs and not pending:
            return []
        groups = finalize_groups(self._conn, pending)
        scores = self._materialized_scores(contribs, groups)
        self._apply_agent_boost(scores, adj)
        self._apply_trust_factor(scores, trusted_origins, untrusted_factor)
        best = self._ranked(scores, groups, adj, max_results * 3)
        return self._fetch_ranked_results(best, filters)

    def _contributions(
        self,
        query_text: str,
        query_embedding: bytes | None,
        w: dict[str, float],
        fusion: tuple[int, int],
        filters: tuple[float, str | None, str | None],
    ) -> tuple[dict[int, list[tuple[int, float]]], list[TieGroup | PendingGroup]]:
        """Each signal's row-by-row credits per id, and its predicate groups
        (column groups still to be counted).

        source: ADR-1109"""
        k, pool = fusion
        vec = self._signal_vector(query_embedding, w.get("vector", 1.0), k, pool)
        heat = (w.get("heat", 0.3), k, pool)
        recency = (w.get("recency", 0.0), k, pool)
        signals = [
            (VEC, (vec, None)),
            (FTS, self._signal_fts(query_text, w.get("fts", 0.5), k, pool)),
            (
                HEAT,
                self._signal_column(HEAT, "heat_base", _HEAT_ORDER, heat, filters),
            ),
            (
                RECENCY,
                self._signal_column(
                    RECENCY, "created_at", _AGE_ORDER, recency, filters
                ),
            ),
        ]
        contribs: dict[int, list[tuple[int, float]]] = {}
        groups: list[TieGroup | PendingGroup] = []
        for signal, (credits, group) in signals:
            for mid, credit in credits:
                contribs.setdefault(mid, []).append((signal, credit))
            if group is not None:
                groups.append(group)
        return contribs, groups

    def _materialized_scores(
        self,
        contribs: dict[int, list[tuple[int, float]]],
        groups: list[TieGroup],
    ) -> dict[int, float]:
        """Fused score of every id scored row by row, including the credit of
        each predicate group it belongs to, summed in signal order.

        source: ADR-1109"""
        if contribs:
            ids = json_ids(contribs)
            for g in groups:
                for r in self._conn.execute(
                    # NOT INDEXED: look the few scored ids up by rowid; the
                    # planner otherwise scans the group's index (8.9 ms at
                    # 250,000 tied rows, 2026-10-16).
                    "SELECT m.id AS id FROM memories m NOT INDEXED "  # noqa: S608 — IDS_IN and the group predicate are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                    f"WHERE m.id {IDS_IN} AND ({g.where})",  # noqa: S608 — IDS_IN and the group predicate are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                    (ids, *g.params),
                ).fetchall():
                    contribs[r["id"]].append((g.signal, g.credit))
        return {mid: ordered_sum(cs) for mid, cs in contribs.items()}

    def _apply_agent_boost(self, scores: dict[int, float], adj: Adjustments) -> None:
        """source: ADR-0616"""
        if not adj.agent_topic or not scores:
            return
        rows = self._conn.execute(
            f"SELECT id FROM memories WHERE id {IDS_IN} AND agent_context = ?",  # noqa: S608 — IDS_IN is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            (json_ids(scores), adj.agent_topic),
        ).fetchall()
        for r in rows:
            scores[r["id"]] += adj.boost

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

    def _ranked(
        self,
        scores: dict[int, float],
        groups: list[TieGroup],
        adj: Adjustments,
        top: int,
    ) -> list[tuple[float, str, int]]:
        """The ``top`` best (score, created_at, id), all descending; exact
        ties go to the newer memory. Rows reached only through predicate
        groups come from ``group_candidates`` (ADR-1109).

        source: ADR-1106"""
        cands = [
            (scores[r["id"]], r["created_at"], r["id"])
            for r in self._conn.execute(
                f"SELECT id, created_at FROM memories WHERE id {IDS_IN}",  # noqa: S608 — IDS_IN is an in-code literal; the ids are one bound parameter (docs/ASSURANCE-CASE.md §5)
                (json_ids(scores),),
            ).fetchall()
        ]
        if groups:
            cands += group_candidates(self._conn, groups, json_ids(scores), adj, top)
        return sorted(cands, reverse=True)[:top]

    def _fetch_ranked_results(
        self,
        best: list[tuple[float, str, int]],
        filters: tuple[float, str | None, str | None],
    ) -> list[dict[str, Any]]:
        """source: ADR-0616"""
        # source: ADR-0616
        row_map = {
            r["id"]: r
            for r in self._conn.execute(
                f"SELECT * FROM current_memories WHERE id {IDS_IN}",  # noqa: S608 — IDS_IN is an in-code literal; the ids are one bound parameter (docs/ASSURANCE-CASE.md §5)
                (json_ids(mid for _, _, mid in best),),
            ).fetchall()
        }
        return [
            _result(mid, row_map[mid], score)
            for score, _, mid in best
            if mid in row_map and _visible(row_map[mid], *filters)
        ]
