"""Integration tests for handlers.consolidation.memory_reheat_pass
(I6-D5, INC6.6) — runs against the shared store wired by conftest (live
PG / dev DB when available; skipped otherwise, matching the rest of the
handler-level test suite's convention).

Covers what the pure core tests cannot: the SQL-level scan+probe
(``effective_heat`` computed by the real PL/pgSQL function, including the
``heat_base=1.0`` clone probe), the CAS-guarded write, the never-lower
invariant against the real function (not just the pure-function
contract), and idempotence of a full pass re-run.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from mcp_server.handlers.consolidation.memory_reheat_pass import (
    run_memory_reheat_pass,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store

# source: ADR-1112 (tests of the store itself run on the in-process store)
pytestmark = pytest.mark.in_process_store


def _store():
    s = get_memory_settings()
    return get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)


def _pg_only():
    store = _store()
    if not hasattr(store, "batch_pool"):
        pytest.skip("memory_reheat_pass requires a PostgreSQL store")
    return store


def _unique_content(label: str) -> str:
    return f"I6-D5 reheat test [{label}] {uuid.uuid4().hex}"


def _insert_deliberate(
    conn,
    *,
    content: str,
    heat_base: float,
    source: str = "lesson",
    no_decay: bool = True,
) -> int:
    """Insert a deliberate-source memory with a controlled heat_base.

    ``no_decay=True`` (default) makes ``effective_heat == heat_base``
    exactly, matching TestProtectedRowShape's derivation in the core
    tests -- deterministic assertions without waiting on the decay curve.
    """
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memories
                   (content, domain, tags, source, heat_base, no_decay, created_at)
               VALUES (%(content)s, '', '[]'::jsonb, %(source)s,
                       %(heat_base)s, %(no_decay)s, NOW())
               RETURNING id""",
            {
                "content": content,
                "source": source,
                "heat_base": heat_base,
                "no_decay": no_decay,
            },
        )
        return cur.fetchone()["id"]


def _fetch_heat_base(conn, memory_id: int) -> float:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT heat_base FROM memories WHERE id = %s", (memory_id,))
        return cur.fetchone()["heat_base"]


def _run(store, *, apply: bool, target: float = 0.25, limit: int = 5000):
    return asyncio.run(
        run_memory_reheat_pass(store, apply=apply, target=target, limit=limit)
    )


class TestBelowTargetIsRaised:
    def test_deliberate_row_below_target_reaches_target(self):
        store = _pg_only()
        content = _unique_content("below-target")
        with store.batch_pool.connection() as conn:
            memory_id = _insert_deliberate(conn, content=content, heat_base=0.10)
            conn.commit()
        try:
            result = _run(store, apply=True)
            entry = next((j for j in result["journal"] if j["id"] == memory_id), None)
            assert entry is not None
            assert entry["outcome"] == "reheated"
            # Slightly above 0.25 by design (_FLOAT32_ROUNDTRIP_MARGIN,
            # core/memory_reheat.py) -- never below, never far above.
            assert entry["heat_base_after"] >= 0.25
            assert entry["heat_base_after"] == pytest.approx(0.25, abs=1e-3)

            with store.batch_pool.connection() as conn:
                heat_base_after = _fetch_heat_base(conn, memory_id)
            # no_decay=True -> effective_heat == heat_base, so raising
            # heat_base to just above 0.25 is the expected write.
            assert heat_base_after >= 0.25
            assert heat_base_after == pytest.approx(0.25, abs=1e-3)
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestNeverLowers:
    def test_row_already_above_target_is_untouched(self):
        store = _pg_only()
        content = _unique_content("already-above")
        with store.batch_pool.connection() as conn:
            memory_id = _insert_deliberate(conn, content=content, heat_base=0.90)
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert not any(j["id"] == memory_id for j in result["journal"])

            with store.batch_pool.connection() as conn:
                heat_base_after = _fetch_heat_base(conn, memory_id)
            assert heat_base_after == pytest.approx(0.90, abs=1e-6)
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()

    def test_new_heat_base_is_never_below_original_across_many_rows(self):
        store = _pg_only()
        ids_and_before = []
        with store.batch_pool.connection() as conn:
            for hb in (0.02, 0.05, 0.10, 0.15, 0.20, 0.24):
                content = _unique_content(f"never-lower-{hb}")
                mid = _insert_deliberate(conn, content=content, heat_base=hb)
                ids_and_before.append((mid, hb))
            conn.commit()
        try:
            _run(store, apply=True)
            with store.batch_pool.connection() as conn:
                for mid, before in ids_and_before:
                    after = _fetch_heat_base(conn, mid)
                    assert after >= before - 1e-9, (
                        f"heat_base LOWERED for id={mid}: {before} -> {after}"
                    )
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)",
                    ([mid for mid, _ in ids_and_before],),
                )
                conn.commit()


class TestAutoCaptureSourceExcluded:
    def test_post_tool_capture_source_is_never_a_candidate(self):
        store = _pg_only()
        content = _unique_content("auto-capture-excluded")
        with store.batch_pool.connection() as conn:
            memory_id = _insert_deliberate(
                conn, content=content, heat_base=0.05, source="post_tool_capture"
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert not any(j["id"] == memory_id for j in result["journal"])
            with store.batch_pool.connection() as conn:
                heat_base_after = _fetch_heat_base(conn, memory_id)
            assert heat_base_after == pytest.approx(0.05, abs=1e-6)
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestRealMechanicalSourceStringsExcluded:
    """INC7.2 regression test. The INC7.1 retro flagged that
    ``_AUTO_AND_MECHANICAL_SOURCES`` compared against ``"seed"``/
    ``"ingest"``/``"cls"`` while the REAL DB values are ``"seed_project"``/
    ``"ingest_codebase"``/``"cls-consolidation"`` (a prefix family) --
    the exact-match ``NOT IN`` filter never excluded any of them. Each
    case here uses the literal real DB source string (measured via
    ``SELECT DISTINCT source FROM memories``, 2026-07-11) so this test
    fails against the pre-fix query and passes against the fix.
    """

    @pytest.mark.parametrize(
        "source",
        [
            "seed_project",
            "ingest_codebase",
            "cls-consolidation",
            "backfill:-Users-test-Developments-Cortex",
        ],
    )
    def test_real_mechanical_or_derived_source_is_never_a_candidate(self, source):
        store = _pg_only()
        content = _unique_content(f"mechanical-excluded-{source}")
        with store.batch_pool.connection() as conn:
            memory_id = _insert_deliberate(
                conn, content=content, heat_base=0.05, source=source
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert not any(j["id"] == memory_id for j in result["journal"]), (
                f"source={source!r} was treated as a deliberate reheat "
                "candidate -- the source-taxonomy filter regressed"
            )
            with store.batch_pool.connection() as conn:
                heat_base_after = _fetch_heat_base(conn, memory_id)
            assert heat_base_after == pytest.approx(0.05, abs=1e-6)
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestDryRun:
    def test_dry_run_writes_nothing(self):
        store = _pg_only()
        content = _unique_content("dry-run")
        with store.batch_pool.connection() as conn:
            memory_id = _insert_deliberate(conn, content=content, heat_base=0.05)
            conn.commit()
        try:
            result = _run(store, apply=False)
            entry = next(j for j in result["journal"] if j["id"] == memory_id)
            assert entry["outcome"] == "reheated"

            with store.batch_pool.connection() as conn:
                heat_base_after = _fetch_heat_base(conn, memory_id)
            assert heat_base_after == pytest.approx(0.05, abs=1e-6)
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestIdempotence:
    def test_rerun_after_apply_does_not_reheat_again(self):
        store = _pg_only()
        content = _unique_content("idempotence")
        with store.batch_pool.connection() as conn:
            memory_id = _insert_deliberate(conn, content=content, heat_base=0.05)
            conn.commit()
        try:
            first = _run(store, apply=True)
            assert any(
                j["id"] == memory_id and j["outcome"] == "reheated"
                for j in first["journal"]
            )

            second = _run(store, apply=True)
            assert not any(j["id"] == memory_id for j in second["journal"])
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestConcurrentRaceIsCounted:
    def test_cas_guard_rejects_write_when_heat_base_changed_between_scan_and_write(
        self,
    ):
        from mcp_server.infrastructure.pg_store_memory_reheat import apply_reheat

        store = _pg_only()
        content = _unique_content("cas-race")
        with store.batch_pool.connection() as conn:
            memory_id = _insert_deliberate(conn, content=content, heat_base=0.05)
            conn.commit()
        try:
            with store.batch_pool.connection() as conn:
                # Simulate a concurrent writer changing heat_base after
                # this campaign's scan captured old_heat_base=0.05.
                conn.execute(
                    "UPDATE memories SET heat_base = 0.30 WHERE id = %s",
                    (memory_id,),
                )
                conn.commit()
                written = apply_reheat(
                    conn, memory_id, old_heat_base=0.05, new_heat_base=0.25
                )
                conn.commit()
            assert written is False
            with store.batch_pool.connection() as conn:
                heat_base_after = _fetch_heat_base(conn, memory_id)
            assert heat_base_after == pytest.approx(0.30, abs=1e-6)
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestUnreachableRowIsReportedNotFabricated:
    def test_row_that_cannot_reach_target_even_at_max_heat_base_stays_unchanged(self):
        """A late-consolidated row whose decay math caps effective_heat
        below target even at heat_base=1.0 is left untouched and counted
        as unreachable, not silently bumped to 1.0 for no functional
        effect."""
        store = _pg_only()
        content = _unique_content("unreachable")
        with store.batch_pool.connection() as conn:
            # Deep decay: heat_base_set_at far in the past, no no_decay
            # override, low heat_base -> effective_heat well under 0.25
            # AND the multiplier so decayed that even heat_base=1.0 stays
            # under 0.25 too (multiplier < 0.25).
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO memories
                           (content, domain, tags, source, heat_base,
                            heat_base_set_at, stage_entered_at,
                            consolidation_stage, created_at)
                       VALUES (%(content)s, '', '[]'::jsonb, 'lesson', 0.02,
                               NOW() - INTERVAL '400 days',
                               NOW() - INTERVAL '400 days',
                               'consolidated', NOW() - INTERVAL '400 days')
                       RETURNING id""",
                    {"content": content},
                )
                memory_id = cur.fetchone()["id"]
            conn.commit()
        try:
            result = _run(store, apply=True)
            entry = next((j for j in result["journal"] if j["id"] == memory_id), None)
            with store.batch_pool.connection() as conn:
                heat_base_after = _fetch_heat_base(conn, memory_id)
            # Either the row was too decayed to even be a candidate (its
            # effective_heat floor already sits >= target from the
            # consolidated-stage floor being close) or it was scanned and
            # marked unreachable; either way heat_base must be untouched.
            assert heat_base_after == pytest.approx(0.02, abs=1e-6)
            if entry is not None:
                assert entry["outcome"] == "unreachable"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()
