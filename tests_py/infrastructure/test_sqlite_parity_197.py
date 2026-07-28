"""SQLite store parity surface added for issue #197 (pyright burn-down).

Every method here previously raised ``AttributeError`` on the SQLite
backend; broad stage boundaries swallowed the error into silent
degradation (the FlashRank shape). These tests pin the parity contract
against a real in-memory store — no mocks on the store side — plus the
two cursor-contract fixes the same change introduced
(``MaterializedCursor.one`` and the compat ``executemany``).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from mcp_server.infrastructure.pg_store_host import MaterializedCursor
from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


def _vec(*values: float) -> bytes:
    """A 384-dim float32 blob (the store's vec0 table dimension), zero-padded."""
    full = np.zeros(384, dtype=np.float32)
    full[: len(values)] = values
    return full.tobytes()


def _mem(content: str, **overrides) -> dict:
    data = {"content": content, "tags": [], "embedding": None}
    data.update(overrides)
    return data


@pytest.fixture()
def store() -> SqliteMemoryStore:
    return SqliteMemoryStore(db_path=":memory:", embedding_dim=384)


class TestAcquireAndExecuteParity:
    def test_acquire_interactive_yields_the_compat_connection(self, store):
        with store.acquire_interactive() as conn:
            assert conn is store._conn

    def test_acquire_batch_yields_the_compat_connection(self, store):
        with store.acquire_batch() as conn:
            assert conn is store._conn

    def test_execute_translates_pg_placeholders(self, store):
        mid = store.insert_memory(_mem("exec parity"))
        rows = store._execute(
            "SELECT id FROM memories WHERE id = %s", (mid,)
        ).fetchall()
        assert [r["id"] for r in rows] == [mid]

    def test_execute_surfaces_untranslatable_sql(self, store):
        # jsonb containment has no SQLite translation: the documented
        # degraded mode is an OperationalError the caller's mechanism
        # boundary observes — never an AttributeError before the query runs.
        with pytest.raises(sqlite3.OperationalError):
            store._execute("SELECT id FROM memories WHERE tags @> %s::jsonb", ("[]",))


class TestGetMemoriesByTag:
    def test_containment_recency_and_limit(self, store):
        first = store.insert_memory(
            _mem("a", tags=["x-tag"], created_at="2026-01-01T00:00:00+00:00")
        )
        second = store.insert_memory(
            _mem("b", tags=["x-tag", "other"], created_at="2026-02-01T00:00:00+00:00")
        )
        store.insert_memory(
            _mem("c", tags=["other"], created_at="2026-03-01T00:00:00+00:00")
        )
        rows = store.get_memories_by_tag("x-tag")
        assert [r["id"] for r in rows] == [second, first]
        assert [r["id"] for r in store.get_memories_by_tag("x-tag", limit=1)] == [
            second
        ]

    def test_stale_rows_are_excluded(self, store):
        mid = store.insert_memory(_mem("stale", tags=["x-tag"]))
        store._conn.execute("UPDATE memories SET is_stale = 1 WHERE id = ?", (mid,))
        store._conn.commit()
        assert store.get_memories_by_tag("x-tag") == []

    def test_no_substring_false_positive(self, store):
        store.insert_memory(_mem("sub", tags=["x-tag-suffix"]))
        assert store.get_memories_by_tag("x-tag") == []


class TestIterMemoriesForDecay:
    def test_single_chunk_matches_get_all(self, store):
        ids = {store.insert_memory(_mem(f"m{i}")) for i in range(3)}
        chunks = list(store.iter_memories_for_decay())
        assert len(chunks) == 1
        assert {m["id"] for m in chunks[0]} == ids
        assert {m["id"] for m in store.get_all_memories_for_decay()} == ids


class TestFindCoAccessedPairs:
    def test_pairs_are_sorted_and_deduplicated(self, store):
        m1 = store.insert_memory(_mem("m1"))
        m2 = store.insert_memory(_mem("m2"))
        e1 = store.insert_entity({"name": "alpha", "type": "concept"})
        e2 = store.insert_entity({"name": "beta", "type": "concept"})
        e3 = store.insert_entity({"name": "gamma", "type": "concept"})
        for eid in (e2, e1):  # insertion order must not matter
            store.insert_memory_entity(m1, eid)
        store.insert_memory_entity(m2, e2)
        store.insert_memory_entity(m2, e3)
        pairs = store.find_co_accessed_pairs([m1, m2])
        assert sorted(pairs) == [(min(e1, e2), max(e1, e2)), (min(e2, e3), max(e2, e3))]

    def test_empty_input_is_empty(self, store):
        assert store.find_co_accessed_pairs([]) == []


class TestSearchNewerNeighbors:
    def test_newer_only_excludes_self_and_orders_by_similarity(self, store):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        target = store.insert_memory(
            _mem("t", embedding=_vec(1, 0, 0), created_at=base.isoformat())
        )
        # Older row: must never appear.
        store.insert_memory(
            _mem(
                "old",
                embedding=_vec(1, 0, 0),
                created_at=(base - timedelta(days=1)).isoformat(),
            )
        )
        store.insert_memory(
            _mem(
                "near",
                embedding=_vec(1, 0.1, 0),
                created_at=(base + timedelta(days=1)).isoformat(),
            )
        )
        store.insert_memory(
            _mem(
                "far",
                embedding=_vec(0, 1, 0),
                created_at=(base + timedelta(days=1)).isoformat(),
            )
        )
        result = store.search_newer_neighbors(
            _vec(1, 0, 0), base.isoformat(), target, top_k=10
        )
        assert len(result) == 2
        similarities = [sim for sim, _age in result]
        assert similarities == sorted(similarities, reverse=True)
        assert similarities[0] > 0.9
        assert all(age >= 0 for _sim, age in result)

    def test_zero_query_vector_yields_no_neighbors(self, store):
        assert store.search_newer_neighbors(_vec(0, 0, 0), "2026-01-01", 1) == []


class TestUpdateForgettingPressureAccum:
    def test_accumulator_is_persisted(self, store):
        mid = store.insert_memory(_mem("p"))
        store.update_forgetting_pressure_accum(mid, 0.73)
        row = store._conn.execute(
            "SELECT forgetting_pressure_accum FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row["forgetting_pressure_accum"] == pytest.approx(0.73)


class TestCompatExecutemany:
    def test_executemany_translates_and_inserts_all_rows(self):
        raw = sqlite3.connect(":memory:")
        raw.row_factory = sqlite3.Row
        conn = PsycopgCompatConnection(raw)
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE t (a INTEGER, b TEXT)")
            cur.executemany(
                "INSERT INTO t (a, b) VALUES (%s, %s)", [(1, "x"), (2, "y")]
            )
        rows = conn.execute("SELECT a, b FROM t ORDER BY a").fetchall()
        assert [(r["a"], r["b"]) for r in rows] == [(1, "x"), (2, "y")]


class TestInsertLastrowidContract:
    def test_missing_lastrowid_raises_with_the_cause(self, store, monkeypatch):
        class _NoRowidCursor:
            lastrowid = None
            rowcount = 1

        monkeypatch.setattr(
            store._conn,
            "execute",
            lambda *a, **k: _NoRowidCursor(),
        )
        with pytest.raises(sqlite3.ProgrammingError, match="no lastrowid"):
            store._insert_memory_rows(_mem("broken"))


class TestMaterializedCursorOne:
    class _FakeCursor:
        def __init__(self, rows):
            self.rowcount = len(rows)
            self._rows = rows

        def fetchall(self):
            return self._rows

    def test_one_returns_the_row(self):
        cur = MaterializedCursor(self._FakeCursor([{"id": 7}]))
        assert cur.one() == {"id": 7}

    def test_one_raises_on_empty_result(self):
        cur = MaterializedCursor(self._FakeCursor([]))
        with pytest.raises(Exception, match="guaranteed a row"):
            cur.one()
