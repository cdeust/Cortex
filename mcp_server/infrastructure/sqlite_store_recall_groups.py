"""Counting a recall's tie groups, and the (origin, agent) pairs inside them.

A heat or recency group past the pool (ADR-1109) is counted once, after every
signal has produced its group, over the group's covering index
``(column, capture_origin, agent_context, created_at, id, filter columns)``.
The count is grouped by (capture_origin, agent_context), which follows the
index order (no sort), and per pair it also totals the rows lying in each
combination of the recall's other groups (a recall with no other group gets
a plain grouped count). One pass therefore gives:

- the group's size, hence the exact shared credit of its rows;
- every (origin, agent) pair present, which the fill reads with one ordered
  seek each instead of scanning the group (``sqlite_store_recall_fill.py``);
- per pair, how many rows each class (set of groups) holds, so classes and
  partitions without a row cost no seek.

When heat and recency are both past the pool, the second group's pass
counts only its rows outside the first group (one exclusion test per row,
no class total); the rows the two share, per pair and per class, are read
from the first group's pass. Inside a group, membership of the other
column group is tested on its column alone: both carry the recall's same
filters.

The pairs are bounded by the store's vocabulary, not by the group: five
capture origins (``core/capture_origin.ALL_ORIGINS``) times the agent
contexts present (owner's store, 2026-10-16: 426 pairs in all, at most 240
in one domain).

source: ADR-1109
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from mcp_server.shared.tie_groups import TieGroup, group_credit

Pair = tuple[str, str | None]


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


Counts = dict[frozenset[int], int]


def finalize_groups(
    conn: PsycopgCompatConnection, items: list[TieGroup | PendingGroup]
) -> list[TieGroup]:
    """Count every pending group (with its pairs and class totals) and give
    it its credit; groups already counted pass through.

    precondition: ``items`` in fusion order.

    source: ADR-1109"""
    out: list[TieGroup] = []
    done: dict[int, dict[Pair, Counts]] = {}
    for i, g in enumerate(items):
        if isinstance(g, TieGroup):
            out.append(g)
            continue
        others = [h for j, h in enumerate(items) if j != i]
        known = [h for h in others if h.signal in done]
        fresh = [h for h in others if h.signal not in done]
        outside = _pair_counts(conn, g, fresh, known)
        by_pair = _with_known(outside, g.signal, others, known, done)
        done[g.signal] = by_pair
        masks = range(2 ** len(others))
        pairs = tuple(
            (o, a, tuple(c[_members(others, m)] for m in masks))
            for (o, a), c in by_pair.items()
        )
        size = sum(c[frozenset()] for c in by_pair.values())
        credit = group_credit(g.head_len, size, g.weight, g.k)
        signals = tuple(h.signal for h in others)
        out.append(
            TieGroup(g.signal, credit, g.where, g.params, g.index, size, signals, pairs)
        )
    return out


def _members(others: list[TieGroup | PendingGroup], mask: int) -> frozenset[int]:
    """The signals whose bit is set in ``mask``.

    source: ADR-1109"""
    return frozenset(h.signal for b, h in enumerate(others) if mask >> b & 1)


def _with_known(
    outside: dict[Pair, Counts],
    signal: int,
    others: list[TieGroup | PendingGroup],
    known: list[TieGroup | PendingGroup],
    done: dict[int, dict[Pair, Counts]],
) -> dict[Pair, Counts]:
    """Every total of ``signal``'s group per pair, from its own pass over the
    rows outside the group counted earlier (``outside``) and from that
    group's pass: per pair, the rows two groups share are the same rows
    whichever index counted them. A total over a set holding the earlier
    group is read from its pass; any other total is the outside part plus
    the shared part.

    precondition: at most one group counted earlier (only heat and recency
    are column groups).

    source: ADR-1109"""
    if not known:
        return outside
    if len(known) > 1:
        raise ValueError("more than two column tie groups in one recall")
    earlier, me = known[0].signal, frozenset({signal})
    theirs = done[earlier]
    pairs = set(outside) | {p for p, c in theirs.items() if c.get(me, 0)}
    result: dict[Pair, Counts] = {}
    for pair in sorted(pairs, key=lambda p: (p[0], p[1] is not None, p[1] or "")):
        counts: Counts = {}
        for mask in range(2 ** len(others)):
            inside = _members(others, mask)
            rest = inside - {earlier}
            shared = theirs.get(pair, {}).get(rest | me, 0)
            mine = 0 if earlier in inside else outside.get(pair, {}).get(rest, 0)
            counts[inside] = shared + mine
        result[pair] = counts
    return result


def _member_test(h: TieGroup | PendingGroup, g: PendingGroup) -> tuple[str, tuple]:
    """SQL true exactly for the rows of ``g`` that lie in ``h``. Two column
    groups of one recall share their filters (``_pending``), so inside ``g``
    the test is ``h``'s column equality alone; anything else is tested whole.

    source: ADR-1109"""
    if isinstance(h, PendingGroup):
        head_h, head_g = f"m.{h.column} = ? AND ", f"m.{g.column} = ? AND "
        same = h.where.removeprefix(head_h) == g.where.removeprefix(head_g)
        if same and h.where.startswith(head_h) and h.params[1:] == g.params[1:]:
            return f"m.{h.column} = ?", (h.params[0],)
    return f"({h.where})", h.params


def _pair_counts(
    conn: PsycopgCompatConnection,
    g: PendingGroup,
    fresh: list[TieGroup | PendingGroup],
    known: list[TieGroup | PendingGroup],
) -> dict[Pair, Counts]:
    """Per (origin, agent) pair, over the rows of ``g`` in none of ``known``:
    their count (key ``frozenset()``) and the count also in every group of
    each non-empty subset of ``fresh``. One index-only pass grouped in index
    order (no sort, no temp B-tree), over ``g.where``: the pairs listed are
    those of the recall's filters, never of other domains. Class counts use
    ``sum(CASE ...)``, not ``count(*) FILTER``, which needs SQLite >= 3.30.

    source: ADR-1109"""
    cols = ["m.capture_origin AS o", "m.agent_context AS a", "count(*) AS t0"]
    params: list[Any] = []
    tests = [_member_test(h, g) for h in fresh]
    for mask in range(1, 2 ** len(fresh)):
        inside = [t for b, t in enumerate(tests) if mask >> b & 1]
        cols.append(
            f"sum(CASE WHEN {' AND '.join(t for t, _ in inside)} THEN 1 ELSE 0 END)"
            f" AS t{mask}"
        )
        params.extend(p for _, ps in inside for p in ps)
    where, wparams = [g.where], list(g.params)
    for test, ps in (_member_test(h, g) for h in known):
        where.append(f"NOT COALESCE({test}, 0)")
        wparams.extend(ps)
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM memories m INDEXED BY {g.index} "  # noqa: S608 — columns, index and predicates are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        f"WHERE {' AND '.join(where)} GROUP BY m.capture_origin, m.agent_context",
        (*params, *wparams),
    ).fetchall()
    masks = range(2 ** len(fresh))
    return {
        (r["o"], r["a"]): {_members(fresh, m): int(r[f"t{m}"]) for m in masks}
        for r in rows
    }


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
