"""fetch_with_ties keeps a boundary tie group whole; tied_rrf shares credit.

source: ADR-1109
"""

from __future__ import annotations

import pytest

from mcp_server.shared.tie_groups import fetch_with_ties, tied_rrf


def fetcher(scores: list[int], calls: list[int]):
    def fetch(n: int) -> list[int]:
        calls.append(n)
        return scores[:n]

    return fetch


@pytest.mark.parametrize(
    ("scores", "pool", "kept"),
    [
        ([9, 8, 7, 6], 2, 2),  # no tie at the cut
        ([9, 8, 8, 8, 8, 8, 7], 2, 6),  # the group runs past the first widening
        ([9, 9, 9], 2, 3),  # the group ends at the last row
        ([9], 3, 1),  # fewer rows than the pool
        ([9, 9, 8, 8], 2, 2),  # a tie that ends exactly at the cut
    ],
)
def test_fetch_with_ties_keeps_rank_le_pool(scores, pool, kept):
    calls: list[int] = []
    got = fetch_with_ties(fetcher(scores, calls), pool, lambda s: s)
    assert got == scores[:kept]
    assert calls[0] == pool + 1


def test_tied_rrf_shares_the_groups_positions():
    credit = tied_rrf([(1, 5), (2, 4), (3, 4), (4, 3)], 1.0, 60)
    assert credit[1] == pytest.approx(1 / 61)
    assert credit[2] == credit[3] == pytest.approx((1 / 62 + 1 / 63) / 2)
    assert credit[4] == pytest.approx(1 / 64)
    assert sum(credit.values()) == pytest.approx(sum(1 / (60 + r) for r in range(1, 5)))
