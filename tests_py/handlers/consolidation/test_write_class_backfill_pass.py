"""Integration tests for handlers.consolidation.write_class_backfill_pass
(M-D2, 7.4) — runs against the shared store wired by conftest (live PG /
``cortex_test`` when available; skipped otherwise, matching
test_memory_domain_backfill_pass.py's convention).

Covers what the pure core tests (test_write_class.py) cannot: the
SQL-level guarantees — the group-by-source bulk UPDATE, the
never-touch-an-explicit-non-default-value guard, and idempotence of a
full pass re-run.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers.consolidation.write_class_backfill_pass import (
    run_write_class_backfill_pass,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store

# source: ADR-1112 (tests of the store itself run on the in-process store)
pytestmark = pytest.mark.in_process_store


def _store():
    s = get_memory_settings()
    return get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)


def _pg_only():
    """Skip when the shared store isn't PostgreSQL (no batch_pool)."""
    store = _store()
    if not hasattr(store, "batch_pool"):
        pytest.skip("write_class_backfill_pass requires a PostgreSQL store")
    return store


def _insert_raw_memory(
    conn, *, content: str, source: str, write_class: str = "deliberate"
) -> int:
    """Insert a memory row with fully-controlled source/write_class
    columns, bypassing remember's own classification so the fixture is
    exact."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memories (content, source, write_class)
               VALUES (%(content)s, %(source)s, %(write_class)s)
               RETURNING id""",
            {"content": content, "source": source, "write_class": write_class},
        )
        return cur.fetchone()["id"]


def _fetch_write_class(conn, memory_id: int) -> str:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT write_class FROM memories WHERE id = %s", (memory_id,))
        return cur.fetchone()["write_class"]


def _run(store, *, apply: bool, limit: int = 5000):
    return asyncio.run(run_write_class_backfill_pass(store, apply=apply, limit=limit))


class TestReclassification:
    def test_auto_source_at_default_gets_reclassified(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn, content="7.4 test: auto source", source="post_tool_capture"
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert result["status"] == "ok"
            assert any(
                j["source"] == "post_tool_capture" and j["to"] == "auto"
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                assert _fetch_write_class(conn, memory_id) == "auto"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()

    def test_derived_source_at_default_gets_reclassified(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn, content="7.4 test: derived source", source="cls-consolidation"
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert any(
                j["source"] == "cls-consolidation" and j["to"] == "derived"
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                assert _fetch_write_class(conn, memory_id) == "derived"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()

    def test_mechanical_source_at_default_gets_reclassified(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn, content="7.4 test: mechanical source", source="ingest_codebase"
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert any(
                j["source"] == "ingest_codebase" and j["to"] == "mechanical"
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                assert _fetch_write_class(conn, memory_id) == "mechanical"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestGenuinelyDeliberateUnchanged:
    def test_deliberate_source_at_default_stays_deliberate_not_journaled(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn, content="7.4 test: genuinely deliberate", source="feature"
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert not any(j["source"] == "feature" for j in result["journal"])
            with store.batch_pool.connection() as conn:
                assert _fetch_write_class(conn, memory_id) == "deliberate"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestNeverTouchesExplicitNonDefault:
    def test_row_already_explicitly_classified_is_never_touched(self):
        """A post-7.4 writer already set write_class explicitly — even
        though its source string would classify differently, the SQL
        guard (write_class = 'deliberate') never selects this row."""
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="7.4 test: already explicitly classified",
                source="post_tool_capture",
                write_class="mechanical",
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert not any(
                j["source"] == "post_tool_capture" and j.get("row_count", 0) > 0
                for j in result["journal"]
                if j.get("to") != "mechanical"
            )
            with store.batch_pool.connection() as conn:
                # Untouched: still 'mechanical', never reclassified to 'auto'.
                assert _fetch_write_class(conn, memory_id) == "mechanical"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestIdempotence:
    def test_rerun_after_apply_is_a_no_op(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            auto_id = _insert_raw_memory(
                conn, content="7.4 test: idempotence auto", source="post_tool_capture"
            )
            deliberate_id = _insert_raw_memory(
                conn, content="7.4 test: idempotence deliberate", source="lesson"
            )
            conn.commit()
        try:
            first = _run(store, apply=True)
            assert any(j["source"] == "post_tool_capture" for j in first["journal"])

            second = _run(store, apply=True)
            assert not any(
                j["source"] == "post_tool_capture" for j in second["journal"]
            )
            assert second["reclassified_rows"] == 0

            with store.batch_pool.connection() as conn:
                assert _fetch_write_class(conn, auto_id) == "auto"
                assert _fetch_write_class(conn, deliberate_id) == "deliberate"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)",
                    ([auto_id, deliberate_id],),
                )
                conn.commit()


class TestDryRun:
    def test_dry_run_writes_nothing(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn, content="7.4 test: dry run must not write", source="seed_project"
            )
            conn.commit()
        try:
            result = _run(store, apply=False)
            assert any(
                j["source"] == "seed_project" and j["to"] == "mechanical"
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                assert _fetch_write_class(conn, memory_id) == "deliberate"  # unchanged
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestBulkUpdateTouchesWholeGroup:
    def test_multiple_rows_sharing_source_all_reclassified_in_one_pass(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            ids = [
                _insert_raw_memory(
                    conn, content=f"7.4 test: bulk group {i}", source="codebase_analyze"
                )
                for i in range(3)
            ]
            conn.commit()
        try:
            result = _run(store, apply=True)
            entry = next(
                j for j in result["journal"] if j["source"] == "codebase_analyze"
            )
            assert entry["to"] == "mechanical"
            assert entry["row_count"] == 3
            with store.batch_pool.connection() as conn:
                for mid in ids:
                    assert _fetch_write_class(conn, mid) == "mechanical"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = ANY(%s)", (ids,))
                conn.commit()
