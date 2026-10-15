"""SQLite recall signals read from sqlite-vec and stored columns.

Each signal keeps its whole boundary tie group and gives the rows of a tie
group the mean rank credit of the positions they occupy (ADR-1109). A group
that runs past the pool is not read row by row: every member has the same
credit, so it is returned as a ``TieGroup`` (an SQL predicate on
``memories m`` plus that credit) and the fusion fills from it newest first.
Sets of ids go to SQLite as one JSON array read through ``json_each``, so no
statement depends on the build's bind-variable limit.

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
from mcp_server.shared.tie_groups import TieGroup, group_credit, ranked_credits

# source: sqlite-vec v0.1.9, sqlite-vec.c: `#define SQLITE_VEC_VEC0_K_MAX 4096`,
# checked in vec0Filter_knn ("k value in knn query too large").
VEC0_K_MAX = 4096

# Fusion order of the signals: scores add up in this order (ADR-1109).
VEC, HEAT, RECENCY = 0, 2, 3  # FTS = 1 (sqlite_store_search.py)

# source: ADR-1109 -- the index serving each column group's equality in
# created_at DESC, id DESC order (sqlite_schema.py INDEXES_DDL); named with
# INDEXED BY, because without ANALYZE statistics the planner prefers the
# narrower (heat_base) index and sorts the whole group (measured 2026-10-16:
# count 7.6 ms, fill 11.6 ms with a temp B-tree, 40,000 rows at one heat).
_GROUP_INDEX = {
    "heat_base": "idx_memories_heat_base_created_at",
    "created_at": "idx_memories_created_at",
}

# One bound parameter, a JSON array of ids.
IDS_IN = "IN (SELECT value FROM json_each(?))"


def json_ids(ids: Iterable[int]) -> str:
    """Encode ids for ``IDS_IN``.

    source: ADR-1109"""
    return json.dumps(list(ids))


Credits = list[tuple[int, float]]


class SqliteRecallSignalsMixin(SqliteSearchMixin):
    """Vector, heat and recency signals of the SQLite recall fusion."""

    def _signal_vector(
        self, query_embedding: bytes | None, weight: float, k: int, pool: int
    ) -> Credits:
        """Rank-fuse the vector pool. A failure raises: dropping the vector
        signal silently would change every ranking without a trace.

        source: ADR-1109"""
        if not self._has_vec or query_embedding is None or weight <= 0:
            return []
        vec = self._bytes_to_vector(query_embedding)
        if vec is None:
            return []
        rows = self._vec_pool_with_ties(vec.tobytes(), pool)
        # source: ADR-0616
        keep = self._vec_rows_in_query_space([r["rowid"] for r in rows])
        ranked = [(r["rowid"], r["distance"]) for r in rows if r["rowid"] in keep]
        return ranked_credits(ranked, weight, k)

    def _vec_pool_with_ties(self, query: bytes, pool: int) -> list[Any]:
        """The ``pool`` nearest rows plus every row at the pool's last distance.

        postcondition: rows in distance order. The vec0 KNN serves k up to
        ``VEC0_K_MAX`` (8.5 ms at 40,000 rows against 345 ms for a scalar
        scan, 2026-10-15); a pool needing more, or a boundary group still
        open at that k, is read with the scalar ``vec_distance_l2``, which
        computes the same ``distance_l2_sqr_float`` as the KNN.

        source: ADR-1109"""
        k = pool + 1
        if k > VEC0_K_MAX:
            rows = self._vec_scalar(query, f"ORDER BY distance LIMIT {k}", ())
        else:
            rows = self._vec_knn(query, k)
        if len(rows) <= pool or rows[pool]["distance"] != rows[pool - 1]["distance"]:
            return rows[:pool]
        boundary = rows[pool - 1]["distance"]
        while len(rows) == k and rows[-1]["distance"] == boundary and k < VEC0_K_MAX:
            k = min(2 * k, VEC0_K_MAX)
            rows = self._vec_knn(query, k)
        if len(rows) == k and rows[-1]["distance"] == boundary:
            head = [r for r in rows if r["distance"] < boundary]
            tied = self._vec_scalar(
                query, "WHERE distance = ? ORDER BY rowid", (boundary,)
            )
            return head + tied
        return [r for r in rows if r["distance"] <= boundary]

    def _vec_knn(self, query: bytes, k: int) -> list[Any]:
        """source: ADR-1109"""
        return self._conn.execute(
            "SELECT rowid, distance FROM memories_vec "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (query, k),
        ).fetchall()

    def _vec_scalar(self, query: bytes, tail: str, params: tuple) -> list[Any]:
        """source: ADR-1109"""
        return self._conn.execute(
            "SELECT rowid, distance FROM (SELECT rowid, "  # noqa: S608 — tail is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"vec_distance_l2(embedding, ?) AS distance FROM memories_vec) {tail}",
            (query, *params),
        ).fetchall()

    def _vec_rows_in_query_space(self, rowids: list[int]) -> set[int]:
        """Subset of ``rowids`` whose embedding space matches the query's.

        precondition: ``rowids`` are memory ids returned by the vec KNN.
        postcondition: a neural query keeps 'neural' and legacy '' rows; a
        fallback query keeps only 'fallback' rows; an 'unknown' mode (no
        engine constructed, e.g. a raw-vector unit test) keeps everything.
        Fail-open on a missing column.

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

    def _signal_column(
        self,
        signal: int,
        column: str,
        order: str,
        fusion: tuple[float, int, int],
        filters: tuple[float, str | None, str | None],
    ) -> tuple[Credits, TieGroup | None]:
        """Rank-fuse one stored column (``fusion`` = weight, k, pool). A
        boundary group past the pool comes back as a ``TieGroup``.

        source: ADR-1109"""
        weight, k, pool = fusion
        if weight <= 0:
            return [], None
        conds, params = self._build_filter(*filters)
        select = f"FROM current_memories WHERE {' AND '.join(conds)}"  # noqa: S608 — column, order and conditions are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        rows = self._conn.execute(
            f"SELECT id, {column} AS score {select} ORDER BY {order} LIMIT ?",
            [*params, pool + 1],
        ).fetchall()
        if len(rows) <= pool or rows[pool]["score"] != rows[pool - 1]["score"]:
            return ranked_credits(
                [(r["id"], r["score"]) for r in rows[:pool]], weight, k
            ), None
        boundary = rows[pool - 1]["score"]
        head = [(r["id"], r["score"]) for r in rows[:pool] if r["score"] != boundary]
        m_conds, _ = self._build_filter(*filters, alias="m.")
        where = " AND ".join(
            [f"m.{column} = ?", "m.superseded_by_id IS NULL", *m_conds]
        )
        index = _GROUP_INDEX[column]
        size = self._conn.execute(
            f"SELECT count(*) AS n FROM memories m INDEXED BY {index} WHERE {where}",  # noqa: S608 — index and predicate are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            [boundary, *params],
        ).fetchall()[0]["n"]
        credit = group_credit(len(head), size, weight, k)
        group = TieGroup(signal, credit, where, (boundary, *params), index)
        return ranked_credits(head, weight, k), group

    @staticmethod
    def _build_filter(
        min_heat: float,
        domain: str | None,
        directory: str | None,
        alias: str = "",
    ) -> tuple[list[str], list[Any]]:
        """source: ADR-0616"""
        a = alias
        conds = [f"{a}heat_base >= ?", f"NOT {a}is_stale"]
        params: list[Any] = [min_heat]
        if domain:
            conds.append(f"({a}domain = ? OR {a}is_global = 1)")
            params.append(domain)
        if directory:
            conds.append(f"({a}directory_context = ? OR {a}is_global = 1)")
            params.append(directory)
        return conds, params
