"""Integration tests for handlers.consolidation.memory_dedup_exact_pass
(I6-D1, INC6.3) — runs against the shared store wired by conftest (live
PG / ``cortex_test`` when available; skipped otherwise, matching the
rest of the handler-level test suite's convention).

Covers what the pure core tests cannot: the SQL-level grouping
(md5-normalized content match), the CAS-guarded supersede-to-existing
write, non-mutation of content/tags/domain, and idempotence of a full
pass re-run.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from mcp_server.handlers.consolidation.memory_dedup_exact_pass import (
    run_memory_dedup_exact_pass,
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
        pytest.skip("memory_dedup_exact_pass requires a PostgreSQL store")
    return store


def _unique_content(label: str) -> str:
    # uuid4 keeps each test's group isolated from the real dev-DB corpus
    # and from other tests running concurrently against the same DB.
    return f"I6-D1 dedup test [{label}] {uuid.uuid4().hex}"


def _insert_raw_memory(
    conn,
    *,
    content: str,
    heat_base: float,
    domain: str = "",
    tags: list[str] | None = None,
    created_at: str | None = None,
) -> int:
    """Insert a memory row with fully-controlled heat, bypassing decay
    (``no_decay=TRUE``) so ``effective_heat`` == ``heat_base`` exactly —
    deterministic elections without waiting on the decay curve."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memories
                   (content, domain, tags, source, heat_base, no_decay, created_at)
               VALUES (%(content)s, %(domain)s, %(tags)s::jsonb, 'test',
                       %(heat_base)s, TRUE,
                       COALESCE(%(created_at)s::timestamptz, NOW()))
               RETURNING id""",
            {
                "content": content,
                "domain": domain,
                "tags": json.dumps(tags or []),
                "heat_base": heat_base,
                "created_at": created_at,
            },
        )
        return cur.fetchone()["id"]


def _fetch_row(conn, memory_id: int) -> dict:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, content, domain, tags, superseded_by_id, is_stale "
            "FROM memories WHERE id = %s",
            (memory_id,),
        )
        return cur.fetchone()


def _run(store, *, apply: bool, limit: int = 5000):
    return asyncio.run(run_memory_dedup_exact_pass(store, apply=apply, limit=limit))


class TestGroupingAndSurvivorElection:
    def test_hottest_member_survives_others_superseded(self):
        store = _pg_only()
        content = _unique_content("hottest-survives")
        with store.batch_pool.connection() as conn:
            cold_id = _insert_raw_memory(conn, content=content, heat_base=0.1)
            hot_id = _insert_raw_memory(conn, content=content, heat_base=0.9)
            mid_id = _insert_raw_memory(conn, content=content, heat_base=0.5)
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert result["status"] == "ok"
            group = next(j for j in result["journal"] if j["survivor_id"] == hot_id)
            assert set(group["superseded_ids"]) == {cold_id, mid_id}
            assert group["group_size"] == 3

            with store.batch_pool.connection() as conn:
                hot_row = _fetch_row(conn, hot_id)
                cold_row = _fetch_row(conn, cold_id)
                mid_row = _fetch_row(conn, mid_id)
            assert hot_row["superseded_by_id"] is None
            assert cold_row["superseded_by_id"] == hot_id
            assert mid_row["superseded_by_id"] == hot_id
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)",
                    ([cold_id, hot_id, mid_id],),
                )
                conn.commit()

    def test_non_duplicate_singleton_is_never_touched(self):
        store = _pg_only()
        content = _unique_content("singleton")
        with store.batch_pool.connection() as conn:
            solo_id = _insert_raw_memory(conn, content=content, heat_base=0.5)
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert not any(
                solo_id in (j["survivor_id"], *j["superseded_ids"])
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, solo_id)
            assert row["superseded_by_id"] is None
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (solo_id,))
                conn.commit()


class TestTieBreakByCreatedAt:
    def test_equal_heat_oldest_row_survives(self):
        store = _pg_only()
        content = _unique_content("tie-break")
        with store.batch_pool.connection() as conn:
            older_id = _insert_raw_memory(
                conn, content=content, heat_base=0.4, created_at="2020-01-01T00:00:00Z"
            )
            newer_id = _insert_raw_memory(
                conn, content=content, heat_base=0.4, created_at="2026-01-01T00:00:00Z"
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            group = next(
                j
                for j in result["journal"]
                if older_id in (j["survivor_id"], *j["superseded_ids"])
            )
            assert group["survivor_id"] == older_id
            assert group["superseded_ids"] == [newer_id]
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)", ([older_id, newer_id],)
                )
                conn.commit()


class TestMetadataNotMerged:
    """I6-D1: pure edge write, content/tags/domain untouched on every row
    (constraint #3 — no absorption; divergent metadata stays queryable by
    id on the superseded rows, journal records the distinct domains seen)."""

    def test_divergent_tags_and_domains_are_preserved_unmerged(self):
        store = _pg_only()
        content = _unique_content("metadata-divergent")
        with store.batch_pool.connection() as conn:
            survivor_id = _insert_raw_memory(
                conn, content=content, heat_base=0.9, domain="domain-a", tags=["tag-a"]
            )
            other_id = _insert_raw_memory(
                conn, content=content, heat_base=0.1, domain="domain-b", tags=["tag-b"]
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            group = next(
                j for j in result["journal"] if j["survivor_id"] == survivor_id
            )
            assert set(group["domains"]) == {"domain-a", "domain-b"}

            with store.batch_pool.connection() as conn:
                survivor_row = _fetch_row(conn, survivor_id)
                other_row = _fetch_row(conn, other_id)
            # Survivor: completely untouched.
            assert survivor_row["domain"] == "domain-a"
            assert survivor_row["tags"] == ["tag-a"]
            # Superseded: content/tags/domain untouched, only the edge changed —
            # nothing is lost, it is simply no longer a current head.
            assert other_row["domain"] == "domain-b"
            assert other_row["tags"] == ["tag-b"]
            assert other_row["superseded_by_id"] == survivor_id
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)",
                    ([survivor_id, other_id],),
                )
                conn.commit()


class TestDryRun:
    def test_dry_run_writes_nothing(self):
        store = _pg_only()
        content = _unique_content("dry-run")
        with store.batch_pool.connection() as conn:
            a_id = _insert_raw_memory(conn, content=content, heat_base=0.9)
            b_id = _insert_raw_memory(conn, content=content, heat_base=0.1)
            conn.commit()
        try:
            result = _run(store, apply=False)
            assert result["superseded_total"] == 1
            with store.batch_pool.connection() as conn:
                a_row = _fetch_row(conn, a_id)
                b_row = _fetch_row(conn, b_id)
            assert a_row["superseded_by_id"] is None
            assert b_row["superseded_by_id"] is None
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = ANY(%s)", ([a_id, b_id],))
                conn.commit()


class TestIdempotence:
    def test_rerun_after_apply_finds_no_more_groups_for_this_content(self):
        store = _pg_only()
        content = _unique_content("idempotence")
        with store.batch_pool.connection() as conn:
            a_id = _insert_raw_memory(conn, content=content, heat_base=0.9)
            b_id = _insert_raw_memory(conn, content=content, heat_base=0.1)
            c_id = _insert_raw_memory(conn, content=content, heat_base=0.5)
            conn.commit()
        try:
            first = _run(store, apply=True)
            assert any(j["survivor_id"] == a_id for j in first["journal"])

            second = _run(store, apply=True)
            assert not any(
                a_id in (j["survivor_id"], *j["superseded_ids"])
                for j in second["journal"]
            )
            assert not any(
                b_id in (j["survivor_id"], *j["superseded_ids"])
                for j in second["journal"]
            )
            assert not any(
                c_id in (j["survivor_id"], *j["superseded_ids"])
                for j in second["journal"]
            )
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)", ([a_id, b_id, c_id],)
                )
                conn.commit()


class TestSupersedeToExistingCasGuard:
    """Direct unit coverage of pg_store_memory_dedup.supersede_to_existing's
    CAS guard — the mechanism I6-D1 calls "mode batch «supersede-vers-
    existant»". Exercised directly (not just through the pass) so the two
    guard branches (already-superseded duplicate, non-head survivor) are
    each independently provable rather than incidentally hit."""

    def test_rejects_when_duplicate_already_superseded(self):
        store = _pg_only()
        from mcp_server.infrastructure.pg_store_memory_dedup import (
            supersede_to_existing,
        )

        content = _unique_content("cas-dup-already-superseded")
        with store.batch_pool.connection() as conn:
            survivor_id = _insert_raw_memory(conn, content=content, heat_base=0.9)
            duplicate_id = _insert_raw_memory(conn, content=content, heat_base=0.1)
            other_head_id = _insert_raw_memory(conn, content=content, heat_base=0.5)
            conn.commit()
        try:
            with store.batch_pool.connection() as conn:
                first = supersede_to_existing(conn, duplicate_id, survivor_id)
                conn.commit()
                assert first is True
                # Re-applying to the now-superseded duplicate must be a no-op.
                second = supersede_to_existing(conn, duplicate_id, other_head_id)
                conn.commit()
                assert second is False
                row = _fetch_row(conn, duplicate_id)
            assert row["superseded_by_id"] == survivor_id  # unchanged by the 2nd call
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)",
                    ([survivor_id, duplicate_id, other_head_id],),
                )
                conn.commit()

    def test_rejects_when_survivor_is_no_longer_a_chain_head(self):
        store = _pg_only()
        from mcp_server.infrastructure.pg_store_memory_dedup import (
            supersede_to_existing,
        )

        content = _unique_content("cas-survivor-not-head")
        with store.batch_pool.connection() as conn:
            old_survivor_id = _insert_raw_memory(conn, content=content, heat_base=0.9)
            new_head_id = _insert_raw_memory(conn, content=content, heat_base=0.95)
            duplicate_id = _insert_raw_memory(conn, content=content, heat_base=0.1)
            conn.commit()
        try:
            with store.batch_pool.connection() as conn:
                # Simulate a concurrent writer superseding old_survivor_id
                # (e.g. a different correction landing between this
                # campaign's scan and its write).
                conn.execute(
                    "UPDATE memories SET superseded_by_id = %s WHERE id = %s",
                    (new_head_id, old_survivor_id),
                )
                conn.commit()
                result = supersede_to_existing(conn, duplicate_id, old_survivor_id)
                conn.commit()
                row = _fetch_row(conn, duplicate_id)
            assert result is False
            assert row["superseded_by_id"] is None  # never orphaned onto a non-head
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)",
                    ([old_survivor_id, new_head_id, duplicate_id],),
                )
                conn.commit()

    def test_raises_on_self_supersede(self):
        store = _pg_only()
        from mcp_server.infrastructure.pg_store_memory_dedup import (
            supersede_to_existing,
        )

        with store.batch_pool.connection() as conn:
            with pytest.raises(ValueError):
                supersede_to_existing(conn, 1, 1)


class TestCaseAndWhitespaceInsensitiveGrouping:
    def test_case_and_extra_whitespace_still_group_together(self):
        store = _pg_only()
        base = f"I6-D1 dedup test [case-ws]  {uuid.uuid4().hex}"
        variant_a = base
        variant_b = base.upper()  # different case
        variant_c = "  ".join(base.split())  # collapses to same after normalization
        with store.batch_pool.connection() as conn:
            id_a = _insert_raw_memory(conn, content=variant_a, heat_base=0.9)
            id_b = _insert_raw_memory(conn, content=variant_b, heat_base=0.5)
            id_c = _insert_raw_memory(conn, content=variant_c, heat_base=0.1)
            conn.commit()
        try:
            result = _run(store, apply=True)
            group = next(j for j in result["journal"] if j["survivor_id"] == id_a)
            assert set(group["superseded_ids"]) == {id_b, id_c}
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)", ([id_a, id_b, id_c],)
                )
                conn.commit()
