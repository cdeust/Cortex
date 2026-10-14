"""Elect a survivor for each group of byte-identical memory duplicates
(I6-D1, INC6.3 batch-collapse campaign).

source: ADR-0198"""

from __future__ import annotations

from typing import NamedTuple

# source: ADR-0198

_MIN_GROUP_SIZE = 2


class DuplicateMember(NamedTuple):
    """One row in an exact-duplicate group, the fields the election needs.

    ``effective_heat`` and ``created_at`` are read-only inputs computed by
    the caller (the DB, via the ``effective_heat()`` stored function, and
    the row's own ``created_at`` column respectively) — this module makes
    no assumption about how they were derived, only that they are
    comparable (``effective_heat`` a float, ``created_at`` any orderable
    value the caller's rows already carry, e.g. ``datetime`` or ISO str).
    """

    id: int
    effective_heat: float
    created_at: object


class ElectionResult(NamedTuple):
    """Outcome of electing one group's survivor.

    source: ADR-0198"""

    survivor_id: int
    superseded_ids: tuple[int, ...]


def election_key(member: DuplicateMember) -> tuple[float, object]:
    """The election order: highest ``effective_heat`` first, then earliest
    ``created_at``. The survivor is the member with the smallest key.

    source: ADR-0198"""
    return (-member.effective_heat, member.created_at)


def elect_survivor(members: list[DuplicateMember]) -> ElectionResult:
    """Elect the group's survivor: highest ``effective_heat``, tie-broken
    by earliest ``created_at``.

    source: ADR-0198"""
    if len(members) < _MIN_GROUP_SIZE:
        raise ValueError(
            f"elect_survivor requires a group of >= 2 duplicate rows, "
            f"got {len(members)}"
        )

    # source: ADR-0198

    survivor = min(members, key=election_key)
    superseded = tuple(m.id for m in members if m.id != survivor.id)
    return ElectionResult(survivor_id=survivor.id, superseded_ids=superseded)


__all__ = ["DuplicateMember", "ElectionResult", "elect_survivor", "election_key"]
