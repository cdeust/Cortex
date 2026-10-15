"""Signal pools that a score tie cannot split, and rank credit shared by a tie.

A recall signal keeps its best ``pool`` rows. When the row at the cut shares
its score with rows past it, which of them the signal keeps is a choice the
score does not make. ``fetch_with_ties`` keeps the whole tied group, the
semantics of SQL's ``FETCH FIRST n ROWS WITH TIES``: a row is in the pool iff
fewer than ``pool`` rows score strictly better.

The SQLite fusion is rank-based, ``w / (k + rank)`` (Cormack, Clarke and
Buettcher, SIGIR 2009). Rows the signal ranks equal must receive equal credit,
whatever order the database returned them in. ``tied_rrf`` gives each row of a
tied group occupying positions a..a+g-1 the mean of ``w / (k + r)`` over those
positions: the expected credit over every ordering of the group, the treatment
of tied scores in McSherry and Najork, "Computing Information Retrieval
Performance Measures Efficiently in the Presence of Tied Scores", ECIR 2008.
The group's total credit equals what any tie-break would have handed out.

source: ADR-1109
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import TypeVar

Row = TypeVar("Row")


def fetch_with_ties(
    fetch: Callable[[int], Sequence[Row]],
    pool: int,
    score: Callable[[Row], Hashable],
) -> list[Row]:
    """The best ``pool`` rows plus every row tied with the last of them.

    precondition: ``fetch(n)`` returns the best ``n`` rows (or all, if fewer)
    ordered by ``score``, best first; ``pool`` >= 1.
    postcondition: a prefix of that order; a row past position ``pool`` is
    included iff its score equals the score at position ``pool``.
    """
    limit = pool + 1
    rows = list(fetch(limit))
    while len(rows) == limit and score(rows[-1]) == score(rows[pool - 1]):
        limit *= 2
        rows = list(fetch(limit))
    if len(rows) <= pool:
        return rows
    boundary = score(rows[pool - 1])
    return rows[:pool] + [r for r in rows[pool:] if score(r) == boundary]


def tied_rrf(
    ranked: Sequence[tuple[int, Hashable]],
    weight: float,
    k: int,
) -> dict[int, float]:
    """RRF credit per id; rows with equal scores share their positions' mean.

    precondition: ``ranked`` is (id, score) ordered best first; equal scores
    are adjacent.
    postcondition: tied ids get equal credit; the sum over a group equals
    ``sum(weight / (k + r))`` over the positions the group occupies.
    """
    credit: dict[int, float] = {}
    start = 0
    while start < len(ranked):
        end = start
        while end + 1 < len(ranked) and ranked[end + 1][1] == ranked[start][1]:
            end += 1
        share = sum(weight / (k + r) for r in range(start + 1, end + 2))
        for mid, _ in ranked[start : end + 1]:
            credit[mid] = share / (end - start + 1)
        start = end + 1
    return credit


def add_credit(scores: dict[int, float], credit: dict[int, float]) -> None:
    """Add one signal's credit into the fused scores.

    postcondition: ``scores[i]`` grows by ``credit[i]`` for every id in
    ``credit``; ids absent from ``scores`` start at 0.
    """
    for mid, c in credit.items():
        scores[mid] = scores.get(mid, 0) + c
