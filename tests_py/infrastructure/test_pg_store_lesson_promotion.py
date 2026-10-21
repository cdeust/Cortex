"""Integration tests for infrastructure.pg_store_lesson_promotion (G-2
grooming, 2026-07-11) — ``count_lesson_promotion_candidates`` must agree
exactly with ``list_lesson_promotion_candidates`` on eligibility, the
only difference being the absence of a ``LIMIT``.

Live-PG tests, same skip convention as
``tests_py/infrastructure/test_pg_store_near_dup.py``.
"""

from __future__ import annotations

import uuid

import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_lesson_promotion import (
    count_lesson_promotion_candidates,
    list_lesson_promotion_candidates,
)

# source: ADR-1112 (tests of the store itself run on the in-process store)
pytestmark = pytest.mark.in_process_store


def _store():
    s = get_memory_settings()
    return get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)


def _pg_only():
    store = _store()
    if not hasattr(store, "batch_pool"):
        pytest.skip("pg_store_lesson_promotion requires a PostgreSQL store")
    return store


def _unique(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:12]}"


def _insert_lesson_memory(
    conn, *, content: str, useful_count: int = 1, access_count: int = 0
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memories
                   (content, domain, tags, source, created_at,
                    useful_count, access_count)
               VALUES (%(content)s, '', '["lesson"]'::jsonb, 'lesson', NOW(),
                       %(useful_count)s, %(access_count)s)
               RETURNING id""",
            {
                "content": content,
                "useful_count": useful_count,
                "access_count": access_count,
            },
        )
        return cur.fetchone()["id"]


def _delete_memory(conn, memory_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM memories WHERE id = %s", (memory_id,))


class TestCountMatchesListEligibility:
    def test_count_includes_a_freshly_inserted_eligible_lesson(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_lesson_memory(
                conn, content=_unique("g2-count"), useful_count=3
            )
            conn.commit()
        try:
            with store.batch_pool.connection() as conn:
                before = count_lesson_promotion_candidates(conn)
                # A big enough limit to make the two queries equivalent
                # on this narrow slice of the table.
                rows = list_lesson_promotion_candidates(conn, limit=100000)
            assert before >= 1
            assert any(r["id"] == memory_id for r in rows)
            assert before == len(rows)
        finally:
            with store.batch_pool.connection() as conn:
                _delete_memory(conn, memory_id)
                conn.commit()

    def test_count_excludes_memory_with_zero_usage_evidence(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_lesson_memory(
                conn,
                content=_unique("g2-nousage"),
                useful_count=0,
                access_count=0,
            )
            conn.commit()
        try:
            with store.batch_pool.connection() as conn:
                rows = list_lesson_promotion_candidates(conn, limit=100000)
            assert not any(r["id"] == memory_id for r in rows)
        finally:
            with store.batch_pool.connection() as conn:
                _delete_memory(conn, memory_id)
                conn.commit()

    def test_count_is_not_bounded_by_a_small_limit(self):
        """The whole point of count_* is to not truncate like list_* does."""
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            ids = [
                _insert_lesson_memory(
                    conn, content=_unique(f"g2-bound-{i}"), useful_count=1
                )
                for i in range(3)
            ]
            conn.commit()
        try:
            with store.batch_pool.connection() as conn:
                total = count_lesson_promotion_candidates(conn)
                capped = list_lesson_promotion_candidates(conn, limit=1)
            assert total >= 3
            assert len(capped) == 1  # list_* respects the limit
        finally:
            with store.batch_pool.connection() as conn:
                for memory_id in ids:
                    _delete_memory(conn, memory_id)
                conn.commit()
