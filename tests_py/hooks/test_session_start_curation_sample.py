"""The SessionStart curation sample sorts three narrow columns, not whole rows.

Before ADR-1107 the sample sorted every live memory with its content, tags and
embedding as sort payload (3 x 128 MB spilled to disk, 13.4 s warm and 55.3 s
cold on 68,496 memories) to keep 500 of them. The statement now picks the 500
ids on three narrow columns and reads only those rows whole; no index is added
(one on ``last_accessed`` was measured and rejected: it ends HOT updates on
every recall). These tests run the real statement on a real PostgreSQL: the
result is the rows the old statement returned, in the same order.

source: ADR-1107
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.hook_queries import _CURATION_SAMPLE_SQL
from tests_py.conftest import _TEST_DB_URL, _USE_PG

pytestmark = pytest.mark.skipif(not _USE_PG, reason="PostgreSQL test database required")

# The statement as it was before ADR-1107: the oracle for "same rows, same order".
_BEFORE = (
    "SELECT m.id FROM memories m JOIN current_memories cm ON cm.id = m.id "
    "WHERE NOT m.is_stale "
    "ORDER BY m.last_accessed DESC NULLS LAST, m.created_at DESC, m.id DESC "
    "LIMIT {limit}"
)
# The old statement in full: wide payload, the production cut, no tie-break.
_BEFORE_WIDE = (
    "SELECT m.id, m.content, m.tags, effective_heat(m, NOW()) AS effective_heat, "
    "m.created_at, m.domain FROM memories m "
    "JOIN current_memories cm ON cm.id = m.id WHERE NOT m.is_stale "
    "ORDER BY m.last_accessed DESC NULLS LAST, m.created_at DESC LIMIT 500"
)
# Rows wide enough that sorting them whole exceeds work_mem (production rows
# average 1.8 kB: plan width 1774, 2026-10-14); parallel workers sort in full
# before the Gather Merge, which is the plan production chose.
_WIDE_BYTES = 2048  # source: EXPLAIN ANALYZE width=1774 on 68,496 live memories
_WIDE_ROWS = 4000  # source: enough rows that three workers each exceed 1 MB
_FORCE_PARALLEL_SORT = (
    "work_mem = '1MB'",
    "parallel_setup_cost = 0",
    "parallel_tuple_cost = 0",
    "min_parallel_table_scan_size = 0",
    "max_parallel_workers_per_gather = 2",
)
_ROWS = 40  # source: any count above the shrunken cut below
_CUT = 7  # source: the production cut (500) shrunk so the test needs 40 rows


@pytest.fixture
def store():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    pg = PgMemoryStore(database_url=_TEST_DB_URL)
    ids = [pg.insert_memory({"content": f"curation row {n}"}) for n in range(_ROWS)]
    # Ties on BOTH timestamps for the first ten, distinct values after.
    pg._conn.execute(
        "UPDATE memories SET last_accessed = NOW() - (LEAST(id - %s, 10) * "
        "INTERVAL '1 hour'), created_at = NOW() - INTERVAL '1 day' "
        "WHERE id = ANY(%s)",
        (min(ids), ids),
    )
    pg._conn.execute("UPDATE memories SET is_stale = TRUE WHERE id = %s", (ids[0],))
    pg._conn.execute(
        "UPDATE memories SET superseded_by_id = %s WHERE id = %s", (ids[2], ids[1])
    )
    pg._conn.execute("ANALYZE memories")
    yield pg, ids
    pg.close()


def _sample(pg, limit: int) -> list[int]:
    sql = _CURATION_SAMPLE_SQL.replace("LIMIT 500", f"LIMIT {limit}")
    assert f"LIMIT {limit}" in sql
    return [row["id"] for row in pg._conn.execute(sql).fetchall()]


def test_the_sample_is_the_rows_the_old_statement_returned_in_the_same_order(store):
    pg, ids = store
    expected = [
        row["id"] for row in pg._conn.execute(_BEFORE.format(limit=_CUT)).fetchall()
    ]
    assert _sample(pg, _CUT) == expected
    assert len(expected) == _CUT


def test_stale_and_superseded_rows_are_never_sampled(store):
    pg, ids = store
    sampled = _sample(pg, _ROWS)
    assert ids[0] not in sampled  # stale
    assert ids[1] not in sampled  # superseded
    assert ids[2] in sampled


def test_no_wide_row_is_sorted_so_nothing_spills_to_disk(store):
    """The pathology: every live row sorted with its content as payload."""
    pg, _ = store
    pg._conn.execute(
        "INSERT INTO memories (content, last_accessed) "
        "SELECT (SELECT string_agg(md5(g::text || i::text), '') "
        "FROM generate_series(1, %s) i), NOW() - g * INTERVAL '1 minute' "
        "FROM generate_series(1, %s) g",
        (_WIDE_BYTES // 32, _WIDE_ROWS),
    )
    pg._conn.execute("ANALYZE memories")
    before = _BEFORE_WIDE
    new = _CURATION_SAMPLE_SQL
    pg._conn.execute("BEGIN")
    try:
        for setting in _FORCE_PARALLEL_SORT:
            pg._conn.execute(f"SET LOCAL {setting}")
        spilled_before = _plan(pg, before)
        spilled_after = _plan(pg, new)
    finally:
        pg._conn.execute("ROLLBACK")
    assert "external merge" in spilled_before, spilled_before  # the premise
    assert "external merge" not in spilled_after, spilled_after


def _plan(pg, sql: str) -> str:
    rows = pg._conn.execute(f"EXPLAIN (ANALYZE) {sql}").fetchall()
    return "\n".join(next(iter(row.values())) for row in rows)
