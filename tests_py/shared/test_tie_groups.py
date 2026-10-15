"""tied_rrf shares a tie group's credit; group_credit and ordered_sum keep
the fusion's exact arithmetic.

source: ADR-1109
"""

from __future__ import annotations

import pytest

from mcp_server.shared.tie_groups import group_credit, ordered_sum, tied_rrf


def test_tied_rrf_shares_the_groups_positions():
    credit = tied_rrf([(1, 5), (2, 4), (3, 4), (4, 3)], 1.0, 60)
    assert credit[1] == pytest.approx(1 / 61)
    assert credit[2] == credit[3] == pytest.approx((1 / 62 + 1 / 63) / 2)
    assert credit[4] == pytest.approx(1 / 64)
    assert sum(credit.values()) == pytest.approx(sum(1 / (60 + r) for r in range(1, 5)))


def test_group_credit_is_tied_rrfs_credit_bit_for_bit():
    ranked = [(i, 0) for i in range(7)]
    assert tied_rrf(ranked, 0.3, 60)[0] == group_credit(0, 7, 0.3, 60)
    head = [(9, 1), (8, 1), (7, 0.5)]
    full = head + [(i, 0) for i in range(20)]
    assert tied_rrf(full, 0.5, 60)[0] == group_credit(len(head), 20, 0.5, 60)


def test_ordered_sum_adds_in_signal_order_from_zero():
    a, b, c = 0.1, 0.2, 0.3
    expected = ((0 + a) + b) + c
    assert ordered_sum([(2, c), (0, a), (1, b)]) == expected
