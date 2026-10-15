"""SQLite recall signals read from sqlite-vec and stored columns.

Each signal keeps its whole boundary tie group and gives the rows of a tie
group the mean rank credit of the positions they occupy (ADR-1109). Sets of
ids go to SQLite as one JSON array read through ``json_each``, so no
statement depends on the build's bind-variable limit
(``SQLITE_MAX_VARIABLE_NUMBER``), however large a tie group is.

source: ADR-0616
source: ADR-1109
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Any

from mcp_server.infrastructure.embedding_engine import current_embedding_mode
from mcp_server.infrastructure.sqlite_store_search import SqliteSearchMixin
from mcp_server.shared.tie_groups import add_credit, tied_rrf

# source: sqlite-vec v0.1.9, sqlite-vec.c: `#define SQLITE_VEC_VEC0_K_MAX 4096`,
# checked in vec0Filter_knn ("k value in knn query too large").
VEC0_K_MAX = 4096

# One bound parameter, a JSON array of ids.
IDS_IN = "IN (SELECT value FROM json_each(?))"


def json_ids(ids: Iterable[int]) -> str:
    """Encode ids for ``IDS_IN``.

    source: ADR-1109"""
    return json.dumps(list(ids))


class SqliteRecallSignalsMixin(SqliteSearchMixin):
    """Vector, heat and recency signals of the SQLite recall fusion."""

    def _signal_vector(
        self,
        scores: dict[int, float],
        query_embedding: bytes | None,
        weight: float,
        k: int,
        pool: int,
    ) -> None:
        """Rank-fuse the KNN pool. A failure raises: dropping the vector
        signal silently would change every ranking without a trace.

        source: ADR-1109"""
        if not self._has_vec or query_embedding is None or weight <= 0:
            return
        vec = self._bytes_to_vector(query_embedding)
        if vec is None:
            return
        rows = self._vec_pool_with_ties(vec.tobytes(), pool)
        # source: ADR-0616
        keep = self._vec_rows_in_query_space([r["rowid"] for r in rows])
        ranked = [(r["rowid"], r["distance"]) for r in rows if r["rowid"] in keep]
        add_credit(scores, tied_rrf(ranked, weight, k))

    def _vec_pool_with_ties(self, query: bytes, pool: int) -> list[Any]:
        """The ``pool`` nearest rows plus every row at the pool's last distance.

        precondition: ``pool + 1 <= VEC0_K_MAX`` (raises ValueError otherwise).
        postcondition: the KNN's own k never exceeds ``pool + 1``; the rest of
        a boundary group is read with sqlite-vec's scalar ``vec_distance_l2``,
        which computes the same ``distance_l2_sqr_float`` as the vec0 KNN
        (sqlite-vec.c), so ``distance = boundary`` matches the KNN's value.

        source: ADR-1109"""
        if pool + 1 > VEC0_K_MAX:
            raise ValueError(
                f"vector pool {pool} needs k={pool + 1}, above sqlite-vec's "
                f"KNN limit {VEC0_K_MAX}"
            )
        rows = self._conn.execute(
            "SELECT rowid, distance FROM memories_vec "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (query, pool + 1),
        ).fetchall()
        if len(rows) <= pool or rows[pool]["distance"] != rows[pool - 1]["distance"]:
            return rows[:pool]
        boundary = rows[pool - 1]["distance"]
        head = [r for r in rows[:pool] if r["distance"] != boundary]
        return (
            head
            + self._conn.execute(
                "SELECT rowid, vec_distance_l2(embedding, ?) AS distance "
                "FROM memories_vec WHERE vec_distance_l2(embedding, ?) = ? "
                "ORDER BY rowid",
                (query, query, boundary),
            ).fetchall()
        )

    def _vec_rows_in_query_space(self, rowids: list[int]) -> set[int]:
        """Subset of ``rowids`` whose embedding space matches the query's.

        precondition: ``rowids`` are memory ids returned by the vec KNN.
        postcondition: returns the ids whose ``memories.embedding_model`` is
        compatible with the current process embedding mode: a neural query
        keeps 'neural' and legacy '' rows; a fallback query keeps only
        'fallback' rows; an 'unknown' mode (no engine constructed, e.g. a
        raw-vector unit test) keeps everything. Fail-open on a missing column.

        source: ADR-0616"""
        if not rowids:
            return set()
        mode = current_embedding_mode()
        if mode == "unknown":
            return set(rowids)
        compatible = {"neural", ""} if mode == "neural" else {"fallback"}
        try:
            rows = self._conn.execute(
                f"SELECT id, embedding_model FROM memories WHERE id {IDS_IN}",  # noqa: S608 — IDS_IN is an in-code literal; the ids are one bound parameter (docs/ASSURANCE-CASE.md §5)
                (json_ids(rowids),),
            ).fetchall()
        except sqlite3.OperationalError:
            return set(rowids)
        return {r["id"] for r in rows if (r["embedding_model"] or "") in compatible}

    def _signal_heat(
        self,
        scores: dict[int, float],
        weight: float,
        k: int,
        pool: int,
        where: tuple[list[str], list[Any]],
    ) -> None:
        if weight <= 0:
            return
        # source: ADR-1106 -- (heat_base DESC, id DESC) keeps the index plan.
        self._signal_column(
            scores, "heat_base", "heat_base DESC, id DESC", (weight, k, pool), where
        )

    def _signal_recency(
        self,
        scores: dict[int, float],
        weight: float,
        k: int,
        pool: int,
        where: tuple[list[str], list[Any]],
    ) -> None:
        if weight <= 0:
            return
        self._signal_column(
            scores, "created_at", "created_at DESC, id DESC", (weight, k, pool), where
        )

    def _signal_column(
        self,
        scores: dict[int, float],
        column: str,
        order: str,
        fusion: tuple[float, int, int],
        where: tuple[list[str], list[Any]],
    ) -> None:
        """Rank-fuse one stored column (``fusion`` = weight, k, pool); its
        boundary tie group is kept whole and tied rows share their positions'
        credit.

        source: ADR-1109"""
        weight, k, pool = fusion
        conds, params = where
        select = (
            f"SELECT id, {column} AS score FROM current_memories "  # noqa: S608 — column and conditions are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"WHERE {' AND '.join(conds)}"
        )
        rows = self._conn.execute(
            f"{select} ORDER BY {order} LIMIT ?", [*params, pool]
        ).fetchall()
        if len(rows) == pool:
            # The whole boundary group in one more query: rows equal to the
            # pool's last score, read back from the same column.
            boundary = rows[-1]["score"]
            head = [r for r in rows if r["score"] != boundary]
            tied = self._conn.execute(
                f"{select} AND {column} = ? ORDER BY {order}", [*params, boundary]
            ).fetchall()
            rows = head + tied
        add_credit(scores, tied_rrf([(r["id"], r["score"]) for r in rows], weight, k))

    @staticmethod
    def _build_filter(
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> tuple[list[str], list[Any]]:
        """source: ADR-0616"""
        conds = ["heat_base >= ?", "NOT is_stale"]
        params: list[Any] = [min_heat]
        if domain:
            conds.append("(domain = ? OR is_global = 1)")
            params.append(domain)
        if directory:
            conds.append("(directory_context = ? OR is_global = 1)")
            params.append(directory)
        return conds, params
