"""Survivor-anchored near-duplicate groups: a member joins a survivor only
when it is itself a near-duplicate of that survivor, never through a chain.

A connected component of candidate pairs at or above the threshold is
single-linkage: A~B and B~C put A and C together whatever sim(A, C) is.
This module turns one component into groups without that transitivity.
The caller elects the survivor of the pending members (``elect_survivor``'s
rule, via ``election_key``), measures the direct similarity of every other
pending member to it, and hands the ids at or above the threshold back to
``settle_round``. Those members join the survivor; the rest stay pending
and form their own groups in the next rounds.

Pure: no I/O. The similarity is measured by the caller.

source: ADR-0370"""

from __future__ import annotations

from collections.abc import Collection

from mcp_server.core.memory_dedup_exact import DuplicateMember, election_key


def election_order(members: list[DuplicateMember]) -> list[DuplicateMember]:
    """Members in election order: the first one is the survivor
    ``elect_survivor`` picks among them, the id breaking a full tie.

    Post-condition: a permutation of ``members``; every suffix of it is
    itself in election order, so the head of the pending suffix is always
    the survivor of the pending members.

    source: ADR-0370"""
    return sorted(members, key=lambda m: (election_key(m), m.id))


def settle_round(
    pending: list[DuplicateMember], near_ids: Collection[int]
) -> tuple[tuple[int, ...], list[DuplicateMember]]:
    """Close one round: ``pending[0]`` is the survivor, ``near_ids`` the
    ids whose direct similarity to it is at or above the threshold.

    Pre-condition: ``pending`` is in election order and not empty.
    Post-condition: (ids that join the survivor, in id order; the members
    left pending, in election order). The survivor is in neither, so every
    round removes at least one member and the rounds terminate. An id of
    ``near_ids`` that is not pending is ignored: only pending members join.

    source: ADR-0370"""
    if not pending:
        raise ValueError("settle_round needs at least the survivor")
    near = set(near_ids)
    rest = pending[1:]
    attached = tuple(sorted(m.id for m in rest if m.id in near))
    remaining = [m for m in rest if m.id not in near]
    return attached, remaining


__all__ = ["election_order", "settle_round"]
