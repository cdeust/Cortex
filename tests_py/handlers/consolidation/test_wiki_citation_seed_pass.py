"""Integration tests for handlers.consolidation.wiki_citation_seed_pass
(M-D7, INC7.7) — runs against the shared store wired by conftest (live
PG / cortex_test DB when available; skipped otherwise, matching the
rest of the handler-level test suite's convention). Never touches the
real ``cortex`` dev DB — ``tests_py/conftest.py`` forces ``DATABASE_URL``
to ``cortex_test`` (CI) or a per-process isolated DB (local).

Covers what the pure core tests cannot: the real SQL join (wiki.pages x
memories), the real ``insert_citation`` write + its unqualified
``ON CONFLICT DO NOTHING`` dedup, and idempotence of a full pass re-run
against the live schema.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

# psycopg ships in the optional [postgresql] extra, absent from the
# SQLite-default install. This module imports it DIRECTLY (below), so without
# this guard it raises ModuleNotFoundError at COLLECTION time — an error, not
# a skip, which fails the whole run (#220). The guard must therefore precede
# the psycopg imports themselves, not just the mcp_server ones.
pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from psycopg.rows import dict_row  # noqa: E402

from mcp_server.handlers.consolidation.wiki_citation_seed_pass import (  # noqa: E402
    run_wiki_citation_seed_pass,
)
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402


def _store():
    s = get_memory_settings()
    return get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)


def _pg_only():
    store = _store()
    if not hasattr(store, "batch_pool"):
        pytest.skip("wiki_citation_seed_pass requires a PostgreSQL store")
    return store


def _unique(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:12]}"


def _insert_memory(conn, *, content: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memories (content, domain, tags, source, created_at)
               VALUES (%(content)s, '', '[]'::jsonb, 'lesson', NOW())
               RETURNING id""",
            {"content": content},
        )
        return cur.fetchone()["id"]


def _insert_page(
    conn, *, rel_path: str, memory_id: int | None, domain: str = ""
) -> int:
    from mcp_server.infrastructure.pg_store_wiki import upsert_page

    slug = rel_path.rsplit("/", 1)[-1].removesuffix(".md")
    page_id, _ = upsert_page(
        conn,
        {
            "memory_id": memory_id,
            "concept_id": None,
            "rel_path": rel_path,
            "slug": slug,
            "kind": "note",
            "title": slug,
            "domain": domain,
            "domains": [],
            "tags": [],
            "audience": [],
            "requires": [],
            "status": "seedling",
            "lifecycle_state": "active",
            "supersedes": None,
            "superseded_by": None,
            "verified": None,
            "lead": "",
            "sections": {},
            "body": "seed-campaign test page",
        },
    )
    return page_id


def _cleanup(conn, *, page_ids: list[int], memory_ids: list[int]) -> None:
    with conn.cursor() as cur:
        if page_ids:
            cur.execute(
                "DELETE FROM wiki.citations WHERE page_id = ANY(%s)", (page_ids,)
            )
            cur.execute("DELETE FROM wiki.pages WHERE id = ANY(%s)", (page_ids,))
        if memory_ids:
            cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (memory_ids,))


def _count_citations(conn, page_id: int) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT count(*) AS n FROM wiki.citations WHERE page_id = %s", (page_id,)
        )
        return cur.fetchone()["n"]


def _run(store, *, apply: bool, limit: int = 5000):
    return asyncio.run(run_wiki_citation_seed_pass(store, apply=apply, limit=limit))


class TestSeedsCitationForPageWithMemoryId:
    def test_dry_run_reports_without_writing(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_memory(conn, content=_unique("i7d7-dryrun"))
            page_id = _insert_page(
                conn,
                rel_path=f"_test/i7d7-{uuid.uuid4().hex[:8]}.md",
                memory_id=memory_id,
                domain="engineering",
            )
        try:
            result = _run(store, apply=False)
            entry = next(
                (j for j in result["journal"] if j["page_id"] == page_id), None
            )
            assert entry is not None
            assert entry["memory_id"] == memory_id
            assert entry["outcome"] == "would_seed"
            assert entry["reliability"] == "high_direct_memory_id"

            with store.batch_pool.connection() as conn:
                assert _count_citations(conn, page_id) == 0  # dry-run wrote nothing
        finally:
            with store.batch_pool.connection() as conn:
                _cleanup(conn, page_ids=[page_id], memory_ids=[memory_id])

    def test_apply_writes_exactly_one_citation_row(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_memory(conn, content=_unique("i7d7-apply"))
            page_id = _insert_page(
                conn,
                rel_path=f"_test/i7d7-{uuid.uuid4().hex[:8]}.md",
                memory_id=memory_id,
                domain="engineering",
            )
        try:
            result = _run(store, apply=True)
            entry = next(
                (j for j in result["journal"] if j["page_id"] == page_id), None
            )
            assert entry is not None
            assert entry["outcome"] == "seeded"

            with (
                store.batch_pool.connection() as conn,
                conn.cursor(row_factory=dict_row) as cur,
            ):
                cur.execute(
                    "SELECT page_id, memory_id, session_id FROM wiki.citations "
                    "WHERE page_id = %s",
                    (page_id,),
                )
                rows = cur.fetchall()
            assert len(rows) == 1
            assert rows[0]["memory_id"] == memory_id
            assert rows[0]["session_id"] == ""
        finally:
            with store.batch_pool.connection() as conn:
                _cleanup(conn, page_ids=[page_id], memory_ids=[memory_id])


class TestIdempotence:
    def test_reapply_seeds_zero_new_rows(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_memory(conn, content=_unique("i7d7-idempotent"))
            page_id = _insert_page(
                conn,
                rel_path=f"_test/i7d7-{uuid.uuid4().hex[:8]}.md",
                memory_id=memory_id,
            )
        try:
            first = _run(store, apply=True)
            assert any(j["page_id"] == page_id for j in first["journal"])

            second = _run(store, apply=True)
            assert not any(j["page_id"] == page_id for j in second["journal"])
            # already_cited must have counted it, not silently dropped it
            with store.batch_pool.connection() as conn:
                assert _count_citations(conn, page_id) == 1
        finally:
            with store.batch_pool.connection() as conn:
                _cleanup(conn, page_ids=[page_id], memory_ids=[memory_id])


class TestPageWithoutMemoryIdIsNeverACandidate:
    def test_null_memory_id_page_is_excluded(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            page_id = _insert_page(
                conn,
                rel_path=f"_test/i7d7-nomem-{uuid.uuid4().hex[:8]}.md",
                memory_id=None,
            )
        try:
            result = _run(store, apply=True)
            assert not any(j["page_id"] == page_id for j in result["journal"])
        finally:
            with store.batch_pool.connection() as conn:
                _cleanup(conn, page_ids=[page_id], memory_ids=[])


class TestPreExistingCitationIsCountedNotDuplicated:
    def test_existing_row_via_insert_citation_is_already_cited(self):
        from mcp_server.infrastructure.pg_store_wiki import insert_citation

        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_memory(conn, content=_unique("i7d7-precited"))
            page_id = _insert_page(
                conn,
                rel_path=f"_test/i7d7-{uuid.uuid4().hex[:8]}.md",
                memory_id=memory_id,
            )
            insert_citation(
                conn, page_id=page_id, session_id="", domain="", memory_id=memory_id
            )
        try:
            result = _run(store, apply=True)
            assert not any(j["page_id"] == page_id for j in result["journal"])
            assert result["already_cited"] >= 1

            with store.batch_pool.connection() as conn:
                assert _count_citations(conn, page_id) == 1  # no duplicate row
        finally:
            with store.batch_pool.connection() as conn:
                _cleanup(conn, page_ids=[page_id], memory_ids=[memory_id])
