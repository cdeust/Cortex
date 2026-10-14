"""Tied rows whose physical order is not their time order (ADR-1106).

Shared by the tie-order tests of the listings that feed recall, the hooks
and the ``include_related`` enrichment. Every row gets one of a few
``created_at`` values, shuffled against insertion order, so neither the
heap order (PostgreSQL) nor the rowid order (SQLite) is the expected
newest-first order, and both keys of ``created_at DESC, id DESC`` decide some
position.

source: ADR-1106
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

# source: test fixture -- more tied rows than every LIMIT under test (the
# largest is get_relationships_for_entity's default 50), so each cut keeps
# only part of the tie.
ROWS = 130
# source: test fixture -- 13 distinct created_at values, 10 rows each.
_STAMPS = 13
# source: test fixture -- fixed seed, the ADR number, so the shuffle repeats.
_SEED = 1106
_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
# Physical orders: as inserted, pseudo-random, reversed.
LAYOUTS = ("inserted", "md5", "reversed")
_CLUSTER_KEYS = {"md5": "(md5(id::text))", "reversed": "((-id))"}


def stamps() -> list[datetime]:
    """created_at per insertion, shuffled so id order is not time order."""
    order = list(range(ROWS))
    random.Random(_SEED).shuffle(order)
    return [_BASE - timedelta(hours=k % _STAMPS) for k in order]


def newest_first(keys: list[tuple[datetime, int]]) -> list[int]:
    """Ids ordered by ``created_at DESC, id DESC``."""
    return [i for _, i in sorted(keys, reverse=True)]


def relayout(conn, table: str, layout: str) -> None:
    """Rewrite ``table``'s heap (and its indexes) in ``layout`` order."""
    if layout != "inserted":
        conn.execute(f"CREATE INDEX ties_layout ON {table} {_CLUSTER_KEYS[layout]}")
        conn.execute(f"CLUSTER {table} USING ties_layout")
        conn.execute("DROP INDEX ties_layout")
    conn.execute(f"VACUUM ANALYZE {table}")


def same_in_every_layout(conn, table: str, read) -> list[int]:
    """Run ``read()`` under every layout; assert one answer; return it."""
    got = {}
    for layout in LAYOUTS:
        relayout(conn, table, layout)
        got[layout] = read()
    assert sorted(got["md5"]) == sorted(got["inserted"]), "row set depends on layout"
    assert sorted(got["reversed"]) == sorted(got["inserted"]), (
        "row set depends on layout"
    )
    assert got["md5"] == got["inserted"] and got["reversed"] == got["inserted"]
    return got["inserted"]
