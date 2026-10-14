"""Tests for core.near_dup_grouping (survivor-anchored groups, ADR-0370)."""

from __future__ import annotations

import pytest

from mcp_server.core.memory_dedup_exact import DuplicateMember, elect_survivor
from mcp_server.core.near_dup_grouping import election_order, settle_round


def _m(mid: int, heat: float, created: int = 0) -> DuplicateMember:
    return DuplicateMember(id=mid, effective_heat=heat, created_at=created)


def test_election_order_head_is_the_elected_survivor():
    members = [_m(5, 0.2), _m(3, 0.9, created=2), _m(7, 0.9, created=1), _m(1, 0.1)]
    ordered = election_order(members)
    assert ordered[0].id == elect_survivor(members).survivor_id == 7
    assert [m.id for m in ordered] == [7, 3, 5, 1]


def test_election_order_breaks_a_full_tie_by_id_whatever_the_input_order():
    tied = [_m(9, 0.5), _m(2, 0.5), _m(4, 0.5)]
    assert [m.id for m in election_order(tied)] == [2, 4, 9]
    assert [m.id for m in election_order(list(reversed(tied)))] == [2, 4, 9]


def test_settle_round_attaches_only_the_survivors_near_duplicates():
    pending = election_order([_m(1, 0.9), _m(2, 0.5), _m(3, 0.2), _m(4, 0.1)])
    attached, remaining = settle_round(pending, {3, 2})
    assert attached == (2, 3)
    assert [m.id for m in remaining] == [4]


def test_settle_round_with_no_near_duplicate_removes_the_survivor_alone():
    pending = election_order([_m(1, 0.9), _m(2, 0.5)])
    attached, remaining = settle_round(pending, set())
    assert attached == ()
    assert [m.id for m in remaining] == [2]


def test_settle_round_ignores_ids_that_are_not_pending():
    pending = election_order([_m(1, 0.9), _m(2, 0.5)])
    attached, remaining = settle_round(pending, {1, 2, 99})
    assert attached == (2,)
    assert remaining == []


def test_settle_round_refuses_an_empty_round():
    with pytest.raises(ValueError):
        settle_round([], set())
