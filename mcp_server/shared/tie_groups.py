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
from itertools import repeat
from operator import truediv
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
    # The same terms in the same order as summing weight / (k + r) over the
    # positions, so the same float; map() runs the loop in C (250,000
    # positions: 8.8 -> 4.3 ms, bit-identical on 20,000 random cases,
    # 2026-10-16).
    first = k + start + 1
    share = sum(map(truediv, repeat(weight, size), range(first, first + size)))
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
        size = end - start + 1
        # A one-row group's credit is its own term (bit-identical); computed
        # inline so the ~300 singletons of a recall do not evict a large
        # group's credit from group_credit's cache.
        share = (
            weight / (k + start + 1)
            if size == 1
            else group_credit(start, size, weight, k)
        )
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
    that serves ``where``'s equality, then (capture_origin, agent_context),
    then ``created_at DESC, id DESC`` order. For an indexed group, ``size``
    is its row count, ``others`` the signals of the other groups of the
    recall, and ``pairs`` one (capture_origin, agent_context, counts) entry
    per pair present in the group, where ``counts[mask]`` is the number of
    the pair's rows that also lie in every other group whose bit is set in
    ``mask`` (``counts[0]`` is the pair's size). ``counts`` is None when the
    recall has no other group: the pair is in the index range, not counted."""

    signal: int
    credit: float
    where: str
    params: tuple[Any, ...]
    index: str | None = None
    size: int = 0
    others: tuple[int, ...] = ()
    pairs: tuple[tuple[str, str | None, tuple[int, ...] | None], ...] = ()


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
