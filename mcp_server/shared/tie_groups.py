"""Rank credit shared by a score tie, and tie groups kept as predicates.

A recall signal keeps its best ``pool`` rows plus every row tied with the last
of them, the semantics of SQL's ``FETCH FIRST n ROWS WITH TIES``: a row is in
the pool iff fewer than ``pool`` rows score strictly better.

The SQLite fusion is rank-based, ``w / (k + rank)`` (Cormack, Clarke and
Buettcher, SIGIR 2009). Rows the signal ranks equal must receive equal credit,
whatever order the database returned them in. ``tied_rrf`` gives each row of a
tied group occupying positions a..a+g-1 the mean of ``w / (k + r)`` over those
positions: the expected credit over every ordering of the group, the treatment
of tied scores in McSherry and Najork, "Computing Information Retrieval
Performance Measures Efficiently in the Presence of Tied Scores", ECIR 2008.
The group's total credit equals what any tie-break would have handed out.

Every row of a group gets the same credit, so a group too large to read row by
row is carried as a ``TieGroup``: a predicate and that one credit.

source: ADR-1109
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# source: ADR-1109 -- one entry per (start, size, weight, k) a recall asks for;
# 256 covers the four signals of many distinct intents and store sizes.
_CREDIT_CACHE = 256


@lru_cache(maxsize=_CREDIT_CACHE)
def group_credit(start: int, size: int, weight: float, k: int) -> float:
    """The credit of each row of a tie group at positions start+1..start+size.

    precondition: ``size`` >= 1.
    postcondition: ``sum(weight / (k + r)) / size`` over those positions,
    summed in position order (the exact arithmetic ``tied_rrf`` uses).
    """
    share = sum(weight / (k + r) for r in range(start + 1, start + size + 1))
    return share / size


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
        share = group_credit(start, end - start + 1, weight, k)
        for mid, _ in ranked[start : end + 1]:
            credit[mid] = share
        start = end + 1
    return credit


def ranked_credits(
    ranked: Sequence[tuple[int, Hashable]], weight: float, k: int
) -> list[tuple[int, float]]:
    """``tied_rrf`` as (id, credit) pairs in rank order."""
    return list(tied_rrf(ranked, weight, k).items())


@dataclass(frozen=True)
class TieGroup:
    """A boundary tie group past the pool: every row satisfying ``where``
    (SQL over ``memories m``, bound with ``params``) gets ``credit`` from the
    signal at fusion position ``signal``. ``index``, when set, is the index
    that serves ``where``'s equality in ``created_at DESC, id DESC`` order."""

    signal: int
    credit: float
    where: str
    params: tuple[Any, ...]
    index: str | None = None


def ordered_sum(contributions: Sequence[tuple[int, float]]) -> float:
    """Sum credits in fusion-signal order, starting from 0.

    postcondition: the same float as adding each signal's credit in turn to
    a score that starts at 0 (the fusion's arithmetic), whatever order the
    contributions were collected in.
    """
    total = 0.0
    for _, credit in sorted(contributions, key=lambda c: c[0]):
        total = total + credit
    return total
