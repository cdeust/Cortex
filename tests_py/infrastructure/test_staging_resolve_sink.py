"""Integration proof of the streaming keyed-ingest path against live PG.

Proves the genius-review fixes end-to-end (DB-backed, not mocked):
  - entity stage resolves ids server-side with NO in-RAM name->id map;
  - the conservation identity ``rows_written + dangling == rows_in`` holds for
    edges (dangling endpoints are COUNTED, never silently swallowed);
  - replay is idempotent — re-running both stages inserts zero net rows
    (the directed unique index + NOT EXISTS make a crashed-then-resumed run
    safe, Dijkstra D2/D5).

Pre: PostgreSQL reachable; entities/relationships tables exist (PgMemoryStore
schema). Post: conservation + idempotency hold.
"""

from __future__ import annotations

import pytest

# psycopg ships in the optional [postgresql] extra, absent from the
# SQLite-default install. This module imports it DIRECTLY (below), so without
# this guard it raises ModuleNotFoundError at COLLECTION time — an error, not
# a skip, which fails the whole run (#220). The guard must therefore precede
# the psycopg imports themselves, not just the mcp_server ones.
pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

import psycopg  # noqa: E402
from psycopg_pool import ConnectionPool  # noqa: E402

from mcp_server.core.streaming.backpressure_pipeline import (  # noqa: E402
    BackpressurePipeline,
    backpressure_pipeline_run,
)
from mcp_server.infrastructure.staging_resolve_sink import (  # noqa: E402
    build_edge_sink,
    build_entity_sink,
)
from tests_py.conftest import _TEST_DB_URL, _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — staging path needs live schema"
)

_MIGRATIONS = [
    "CREATE INDEX IF NOT EXISTS idx_entities_lower_name ON entities (LOWER(name))",
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_indexes
                       WHERE indexname = 'uq_relationships_directed') THEN
            DELETE FROM relationships r USING (
                SELECT source_entity_id, target_entity_id, relationship_type,
                       MIN(id) AS keep_id FROM relationships
                GROUP BY source_entity_id, target_entity_id, relationship_type
                HAVING COUNT(*) > 1) dup
            WHERE r.source_entity_id = dup.source_entity_id
              AND r.target_entity_id = dup.target_entity_id
              AND r.relationship_type = dup.relationship_type
              AND r.id <> dup.keep_id;
            CREATE UNIQUE INDEX uq_relationships_directed
                ON relationships (source_entity_id, target_entity_id,
                                  relationship_type);
        END IF;
    END $$;""",
]


class _ListSource:
    """Yields a fixed list of tuples as ``max_batch``-sized batches."""

    def __init__(self, rows):
        self._rows = rows

    def stream(self, max_batch):
        for i in range(0, len(self._rows), max_batch):
            yield self._rows[i : i + max_batch]


@pytest.fixture
def pg_pool():
    with psycopg.connect(_TEST_DB_URL, autocommit=True) as conn:
        for stmt in _MIGRATIONS:
            conn.execute(stmt)
        conn.execute("TRUNCATE entities, relationships RESTART IDENTITY CASCADE")
    pool = ConnectionPool(
        conninfo=_TEST_DB_URL,
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "row_factory": psycopg.rows.dict_row},
        open=True,
    )
    yield pool
    pool.close()


def _counts(pool):
    with pool.connection() as c:
        e = c.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
        r = c.execute("SELECT COUNT(*) AS n FROM relationships").fetchone()["n"]
    return e, r


def _run(pool):
    entities = [(f"sym_{i}", "function", "verify", 1.0) for i in range(200)]
    edges = [(f"sym_{i}", f"sym_{i + 1}", "calls", 1.0, "verify") for i in range(199)]
    edges += [(f"sym_{i}", f"ghost_{i}", "calls", 1.0, "verify") for i in range(50)]
    ent = BackpressurePipeline(
        source=_ListSource(entities),
        sink_factory=lambda: build_entity_sink(pool.connection),
        max_batch=64,
        queue_cap=4,
        concurrency=1,  # entity stage is single-writer (race-free NOT EXISTS)
    )
    edge = BackpressurePipeline(
        source=_ListSource(edges),
        sink_factory=lambda: build_edge_sink(pool.connection),
        max_batch=64,
        queue_cap=4,
        concurrency=2,
    )
    return ent, edge


def test_resolves_and_conserves(pg_pool):
    ent, edge = _run(pg_pool)
    er = backpressure_pipeline_run(ent)
    rr = backpressure_pipeline_run(edge)
    assert er.errors == [] and rr.errors == []
    n_ent, n_rel = _counts(pg_pool)
    assert n_ent == 200
    assert n_rel == 199  # only fully-resolvable edges land
    # Conservation: every input edge is either written or counted as dangling.
    dangling = rr.rows_in - rr.rows_written
    assert dangling == 50
    assert rr.rows_written + dangling == rr.rows_in


def test_entity_dedup_is_domain_scoped(pg_pool):
    """Same name in TWO domains inserts twice; edges resolve within domain.

    Regression for the 2026-06-11 RCA: a name-global NOT EXISTS made every
    re-ingest a no-op once ANY domain held the name (all code entities
    stayed credited to a stale domain), and an unscoped edge JOIN would
    fan one staged edge into a cross-domain cartesian product.
    """
    ents_a = [(f"dup_{i}", "function", "code:projA", 1.0) for i in range(10)]
    ents_b = [(f"dup_{i}", "function", "code:projB", 1.0) for i in range(10)]
    edges_b = [
        (f"dup_{i}", f"dup_{i + 1}", "calls", 1.0, "code:projB") for i in range(9)
    ]
    for rows, conc in ((ents_a, 1), (ents_b, 1)):
        backpressure_pipeline_run(
            BackpressurePipeline(
                source=_ListSource(rows),
                sink_factory=lambda: build_entity_sink(pg_pool.connection),
                max_batch=64,
                queue_cap=4,
                concurrency=conc,
            )
        )
    rr = backpressure_pipeline_run(
        BackpressurePipeline(
            source=_ListSource(edges_b),
            sink_factory=lambda: build_edge_sink(pg_pool.connection),
            max_batch=64,
            queue_cap=4,
            concurrency=2,
        )
    )
    assert rr.errors == []
    with pg_pool.connection() as c:
        per_domain = c.execute(
            "SELECT domain, COUNT(*) AS n FROM entities "
            "WHERE name LIKE 'dup_%' GROUP BY domain ORDER BY domain"
        ).fetchall()
        # One edge per staged row — endpoints resolved ONLY in code:projB.
        n_rel = c.execute(
            "SELECT COUNT(*) AS n FROM relationships r "
            "JOIN entities s ON s.id = r.source_entity_id "
            "WHERE s.name LIKE 'dup_%'"
        ).fetchone()["n"]
        cross = c.execute(
            "SELECT COUNT(*) AS n FROM relationships r "
            "JOIN entities s ON s.id = r.source_entity_id "
            "JOIN entities t ON t.id = r.target_entity_id "
            "WHERE s.name LIKE 'dup_%' AND s.domain <> t.domain"
        ).fetchone()["n"]
    # trg_entities_domain_normalize lowercases domain on INSERT.
    assert [(row["domain"], row["n"]) for row in per_domain] == [
        ("code:proja", 10),
        ("code:projb", 10),
    ]
    assert n_rel == 9
    assert cross == 0


def test_replay_is_idempotent(pg_pool):
    ent, edge = _run(pg_pool)
    backpressure_pipeline_run(ent)
    backpressure_pipeline_run(edge)
    before = _counts(pg_pool)
    # Re-run both stages — a crashed-then-resumed ingest must add nothing.
    backpressure_pipeline_run(ent)
    backpressure_pipeline_run(edge)
    after = _counts(pg_pool)
    assert after == before == (200, 199)
