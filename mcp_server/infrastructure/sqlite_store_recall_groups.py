"""Counting a recall's tie groups, and the (origin, agent) pairs inside them.

A heat or recency group past the pool (ADR-1109) is counted once, after every
signal has produced its group, over the group's covering index
``(column, capture_origin, agent_context, created_at, id, filter columns)``.
The count is grouped by (capture_origin, agent_context), which follows the
index order (no sort), and per pair it also totals the rows lying in each
combination of the recall's other groups. One pass therefore gives:

- the group's size, hence the exact shared credit of its rows;
- every (origin, agent) pair present, which the fill reads with one ordered
  seek each instead of scanning the group (``sqlite_store_recall_fill.py``);
- per pair, how many rows each class (set of groups) holds, so classes and
  partitions without a row cost no seek.

The pairs are bounded by the store's vocabulary, not by the group: five
capture origins (``core/capture_origin.ALL_ORIGINS``) times the agent
contexts present (owner's store, 2026-10-16: 419 pairs in all, at most 231
in one domain).

source: ADR-1109
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from mcp_server.shared.tie_groups import TieGroup, group_credit


@dataclass(frozen=True)
class PendingGroup:
    """A column group whose size is not counted yet: its predicate, index,
    and what its credit needs (rows ahead of it, weight, k).

    source: ADR-1109"""

    signal: int
    where: str
    params: tuple[Any, ...]
    index: str
    column: str
    head_len: int
    weight: float
    k: int


def finalize_groups(
    conn: PsycopgCompatConnection, items: list[TieGroup | PendingGroup]
) -> list[TieGroup]:
    """Count every pending group (with its pairs and class totals) and give
    it its credit; groups already counted pass through.

    precondition: ``items`` in fusion order.

    source: ADR-1109"""
    out: list[TieGroup] = []
    for i, g in enumerate(items):
        if isinstance(g, TieGroup):
            out.append(g)
            continue
        others = [h for j, h in enumerate(items) if j != i]
        if others:
            pairs = _pair_counts(conn, g, others)
            size = sum(counts[0] for _, _, counts in pairs if counts)
        else:
            size, pairs = _count(conn, g), _pairs_present(conn, g)
        credit = group_credit(g.head_len, size, g.weight, g.k)
        out.append(
            TieGroup(
                g.signal,
                credit,
                g.where,
                g.params,
                g.index,
                size,
                tuple(h.signal for h in others),
                pairs,
            )
        )
    return out


def _pair_counts(
    conn: PsycopgCompatConnection,
    g: PendingGroup,
    others: list[TieGroup | PendingGroup],
) -> tuple[tuple[str, str | None, tuple[int, ...]], ...]:
    """(origin, agent, counts) per pair of ``g``; ``counts[mask]`` = rows also
    in every other group whose bit is set in ``mask``.

    source: ADR-1109"""
    cols = ["m.capture_origin AS o", "m.agent_context AS a", "count(*) AS t0"]
    params: list[Any] = []
    for mask in range(1, 2 ** len(others)):
        inside = [h for b, h in enumerate(others) if mask >> b & 1]
        test = " AND ".join(f"({h.where})" for h in inside)
        cols.append(f"total(CASE WHEN {test} THEN 1 ELSE 0 END) AS t{mask}")
        params.extend(p for h in inside for p in h.params)
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM memories m INDEXED BY {g.index} "  # noqa: S608 — columns, index and predicates are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        f"WHERE {g.where} GROUP BY m.capture_origin, m.agent_context",
        (*params, *g.params),
    ).fetchall()
    masks = range(2 ** len(others))
    return tuple((r["o"], r["a"], tuple(int(r[f"t{m}"]) for m in masks)) for r in rows)


def _count(conn: PsycopgCompatConnection, g: PendingGroup) -> int:
    """The group's size: one index-only range count.

    source: ADR-1109"""
    return int(
        conn.execute(
            f"SELECT count(*) AS n FROM memories m INDEXED BY {g.index} "  # noqa: S608 — index and predicate are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"WHERE {g.where}",
            g.params,
        ).fetchall()[0]["n"]
    )


def _pairs_present(
    conn: PsycopgCompatConnection, g: PendingGroup
) -> tuple[tuple[str, str | None, None], ...]:
    """The (origin, agent) pairs in the group's index range, by a loose index
    scan: one seek per pair, never a pass over the group. Used when the
    recall has no other group, so no class count is needed (counts None:
    every pair is sought; a pair whose rows all fail the filters yields no
    row). The plain count plus this costs 15.9 ms at 250,000 tied rows where
    the grouped pass costs 23.5 ms (2026-10-16).

    source: ADR-1109"""
    head = (
        "SELECT m.capture_origin AS o, m.agent_context AS a "  # noqa: S608 — index and column are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        f"FROM memories m INDEXED BY {g.index} WHERE m.{g.column} = ?"
    )
    order = " ORDER BY m.capture_origin, m.agent_context LIMIT 1"
    boundary = g.params[0]
    pairs: list[tuple[str, str | None, None]] = []
    row = _first(conn, head + order, (boundary,))
    while row is not None:
        origin, agent = row["o"], row["a"]
        pairs.append((origin, agent, None))
        if agent is None:
            same = " AND m.capture_origin = ? AND m.agent_context IS NOT NULL"
            row = _first(conn, head + same + order, (boundary, origin))
        else:
            same = " AND m.capture_origin = ? AND m.agent_context > ?"
            row = _first(conn, head + same + order, (boundary, origin, agent))
        if row is None:
            later = " AND m.capture_origin > ?"
            row = _first(conn, head + later + order, (boundary, origin))
    return tuple(pairs)


def _first(conn: PsycopgCompatConnection, sql: str, params: tuple) -> Any:
    """source: ADR-1109"""
    rows = conn.execute(sql, params).fetchall()
    return rows[0] if rows else None


def class_count(
    anchor: TieGroup, pair_counts: tuple[int, ...], inside: set[int], outside: set[int]
) -> int:
    """Rows of one pair of ``anchor`` that lie in every group of ``inside``
    and in none of ``outside`` (signals), by inclusion-exclusion over the
    pass's totals.

    source: ADR-1109"""
    bit = {s: 1 << b for b, s in enumerate(anchor.others)}
    base = sum(bit[s] for s in inside)
    out_bits = [bit[s] for s in outside]
    total = 0
    for subset in range(2 ** len(out_bits)):
        mask, sign = base, 1
        for b, ob in enumerate(out_bits):
            if subset >> b & 1:
                mask, sign = mask | ob, -sign
        total += sign * pair_counts[mask]
    return total
