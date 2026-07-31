"""Elect a survivor for each group of byte-identical memory duplicates
(I6-D1, INC6.3 batch-collapse campaign).

``memories`` accumulates exact content duplicates (same normalized text,
different rows) because the write-path dedup gate
(``core/curation.py::decide_curation_action``) only runs at ``remember``
time against the CANDIDATE's own near-neighbors — it was never re-applied
retrospectively to the existing stock (I6 audit: 146 active duplicate
rows in 55 groups, 2026-07-10). This module decides, for one already-
grouped set of duplicate rows, which one survives as the current head.

Pure logic, no I/O: the caller (``infrastructure/pg_store_memory_dedup``)
supplies each group's member rows (already fetched from
``current_memories`` and already keyed by the group's content hash); this
module never touches a connection, mirroring
``core/memory_domain_backfill.py``'s DI split (coding-standards.md §2,
Dependency Rule — core imports stdlib only).
"""

from __future__ import annotations

from typing import NamedTuple

# source: structural — a duplicate group has at least two rows by
# construction (see elect_survivor docstring)
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

    ``survivor_id`` is the elected head; ``superseded_ids`` are every
    other member of the group, in the group's original order minus the
    survivor — these are the ids the caller must supersede-to-existing
    (point ``superseded_by_id`` at ``survivor_id``).
    """

    survivor_id: int
    superseded_ids: tuple[int, ...]


def elect_survivor(members: list[DuplicateMember]) -> ElectionResult:
    """Elect the group's survivor: highest ``effective_heat``, tie-broken
    by earliest ``created_at``.

    Pre-condition:  ``members`` has at least 2 entries (a "group" of size
                    1 is not a duplicate group and must not reach this
                    function — the caller's SQL already filters
                    ``HAVING COUNT(*) > 1``) and every member's ``id`` is
                    distinct.
    Post-condition: ``survivor_id`` is the id of the member with the
                    strictly highest ``effective_heat``; when two or more
                    members are tied at the maximum, the one with the
                    earliest ``created_at`` wins (I6-D1: "tie-break : la
                    plus ancienne created_at" — deterministic, no random
                    or insertion-order dependence). ``superseded_ids``
                    contains every other member's id, order-preserved
                    from ``members`` with the survivor removed. The
                    election never depends on anything but the two named
                    fields — no reference to tags/domain/content, which
                    the campaign explicitly does not use as a tie-break
                    (I6-D1: content is identical by construction of the
                    group; tags/domain differences are a separate,
                    explicitly-deferred question, see the campaign
                    report's metadata-preservation decision).
    Raises:         ``ValueError`` if ``members`` has fewer than 2 rows —
                    calling this on a non-group is a caller bug, not a
                    recoverable runtime condition.
    """
    if len(members) < _MIN_GROUP_SIZE:
        raise ValueError(  # noqa: TRY003 — one-off message, not reused (§3.3)
            f"elect_survivor requires a group of >= 2 duplicate rows, "
            f"got {len(members)}"
        )

    # min() with key=(-effective_heat, created_at): negating heat turns
    # "highest heat wins" into "smallest key wins" (heat is a float, so
    # negation is exact); created_at is compared ascending as the second
    # tuple component, so among heat-tied members the smallest (earliest)
    # created_at wins. One pass, one comparator, matches I6-D1's stated
    # priority exactly (heat first, then oldest).
    survivor = min(members, key=lambda m: (-m.effective_heat, m.created_at))
    superseded = tuple(m.id for m in members if m.id != survivor.id)
    return ElectionResult(survivor_id=survivor.id, superseded_ids=superseded)


__all__ = ["DuplicateMember", "ElectionResult", "elect_survivor"]
