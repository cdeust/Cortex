"""Integration tests for handlers.consolidation.memory_domain_backfill_pass
(I6-D3) — runs against the shared store wired by conftest (live PG /
``cortex_test`` when available; skipped otherwise, matching the rest of
the handler-level test suite's convention).

Covers what the pure core tests cannot: the SQL-level guarantees —
non-overwrite of a non-empty domain, orphan tagging, and idempotence of
a full pass re-run.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers.consolidation.memory_domain_backfill_pass import (
    run_memory_domain_backfill_pass,
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
        pytest.skip("memory_domain_backfill_pass requires a PostgreSQL store")
    return store


def _insert_raw_memory(
    conn, *, content: str, domain: str, directory_context: str, tags: list[str]
) -> int:
    """Insert a memory row with fully-controlled domain/evidence columns,
    bypassing remember's own domain resolution so the fixture is exact."""
    import json

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memories (content, domain, directory_context, tags, source)
               VALUES (%(content)s, %(domain)s, %(directory)s, %(tags)s::jsonb, 'test')
               RETURNING id""",
            {
                "content": content,
                "domain": domain,
                "directory": directory_context,
                "tags": json.dumps(tags),
            },
        )
        return cur.fetchone()["id"]


def _fetch_row(conn, memory_id: int) -> dict:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, domain, tags FROM memories WHERE id = %s", (memory_id,))
        return cur.fetchone()


def _run(
    store,
    *,
    apply: bool,
    include_orphans: bool = False,
    resolve_directory=None,
    resolve_project_tag=None,
):
    return asyncio.run(
        run_memory_domain_backfill_pass(
            store,
            apply=apply,
            include_orphans=include_orphans,
            resolve_directory=resolve_directory or (lambda _d: ""),
            resolve_project_tag=resolve_project_tag or (lambda _s: ""),
        )
    )


class TestDirectoryContextBackfill:
    def test_directory_context_evidence_fills_domain(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: directory-context evidence",
                domain="",
                directory_context="/Users/x/Developments/widget-project",
                tags=[],
            )
            conn.commit()
        try:
            result = _run(
                store,
                apply=True,
                resolve_directory=lambda d: "widget-domain" if "widget" in d else "",
            )
            assert result["status"] == "ok"
            assert any(
                j["id"] == memory_id and j["evidence"] == "directory_context"
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == "widget-domain"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestProjectTagBackfill:
    def test_project_tag_evidence_fills_domain(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: project-tag evidence",
                domain="",
                directory_context="",
                tags=["_backfill", "project:my-slug"],
            )
            conn.commit()
        try:
            result = _run(
                store,
                apply=True,
                resolve_project_tag=lambda s: "tagged-domain" if s == "my-slug" else "",
            )
            assert any(
                j["id"] == memory_id and j["evidence"] == "project_tag"
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == "tagged-domain"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestOrphanTagging:
    def test_no_evidence_gets_orphan_tag_domain_stays_empty(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: no evidence at all",
                domain="",
                directory_context="",
                tags=["auto-captured"],
            )
            conn.commit()
        try:
            result = _run(store, apply=True)
            assert any(
                j["id"] == memory_id and j["evidence"] == "" and j["domain"] == ""
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == ""
            assert "domain-orphan" in row["tags"]
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestNonOverwrite:
    def test_non_empty_domain_is_never_touched(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: already has a domain",
                domain="pre-existing-domain",
                directory_context="/Users/x/Developments/widget-project",
                tags=[],
            )
            conn.commit()
        try:
            # This row must never be selected by list_domainless_memories in
            # the first place — assert both the scan and the end state.
            result = _run(
                store,
                apply=True,
                resolve_directory=lambda d: "widget-domain" if "widget" in d else "",
            )
            assert not any(j["id"] == memory_id for j in result["journal"])
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == "pre-existing-domain"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestIdempotence:
    def test_rerun_after_apply_is_a_no_op(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            filled_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: idempotence, directory evidence",
                domain="",
                directory_context="/Users/x/Developments/widget-project",
                tags=[],
            )
            orphan_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: idempotence, orphan",
                domain="",
                directory_context="",
                tags=[],
            )
            conn.commit()
        resolve_directory = lambda d: "widget-domain" if "widget" in d else ""  # noqa: E731
        try:
            first = _run(store, apply=True, resolve_directory=resolve_directory)
            assert any(j["id"] == filled_id for j in first["journal"])
            assert any(j["id"] == orphan_id for j in first["journal"])

            second = _run(store, apply=True, resolve_directory=resolve_directory)
            assert not any(j["id"] == filled_id for j in second["journal"])
            assert not any(j["id"] == orphan_id for j in second["journal"])
            assert second["filled"] == 0
            assert second["orphaned"] == 0

            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, filled_id)
            assert row["domain"] == "widget-domain"
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%s)",
                    ([filled_id, orphan_id],),
                )
                conn.commit()


class TestIncludeOrphansRescan:
    """INC6.2: after a resolution-logic fix (e.g. worktree support in
    domain_mapping.py), a previously-orphaned row can become resolvable.
    ``include_orphans=True`` must rescan it, fill its domain, AND remove
    the stale ``domain-orphan`` tag — the default (``include_orphans=
    False``) must leave it untouched, preserving the standard campaign's
    idempotence guarantee (TestIdempotence above)."""

    def test_default_scan_excludes_orphan_tagged_rows(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: already orphan-tagged, default scan",
                domain="",
                directory_context="/Users/x/Developments/widget-project",
                tags=["domain-orphan"],
            )
            conn.commit()
        try:
            result = _run(
                store,
                apply=True,
                include_orphans=False,
                resolve_directory=lambda d: "widget-domain" if "widget" in d else "",
            )
            assert not any(j["id"] == memory_id for j in result["journal"])
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == ""
            assert "domain-orphan" in row["tags"]
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()

    def test_include_orphans_rescans_and_fills_and_strips_the_tag(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: orphan-tagged, now resolvable on rescan",
                domain="",
                directory_context="/tmp/wt-widget-project",
                tags=["domain-orphan"],
            )
            conn.commit()
        try:
            result = _run(
                store,
                apply=True,
                include_orphans=True,
                # Simulates the worktree fix: the fixed resolve_cwd now
                # resolves this directory where the old logic could not.
                resolve_directory=lambda d: "widget-domain" if "widget" in d else "",
            )
            assert any(
                j["id"] == memory_id and j["evidence"] == "directory_context"
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == "widget-domain"
            assert "domain-orphan" not in row["tags"]
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()

    def test_include_orphans_still_alive_row_stays_orphan_tagged_if_still_unresolvable(
        self,
    ):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: orphan-tagged, still unresolvable",
                domain="",
                directory_context="",
                tags=["domain-orphan"],
            )
            conn.commit()
        try:
            result = _run(store, apply=True, include_orphans=True)
            assert any(
                j["id"] == memory_id and j["evidence"] == "" and j["domain"] == ""
                for j in result["journal"]
            )
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == ""
            assert "domain-orphan" in row["tags"]
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()


class TestDryRun:
    def test_dry_run_writes_nothing(self):
        store = _pg_only()
        with store.batch_pool.connection() as conn:
            memory_id = _insert_raw_memory(
                conn,
                content="I6-D3 test: dry run must not write",
                domain="",
                directory_context="/Users/x/Developments/widget-project",
                tags=[],
            )
            conn.commit()
        try:
            result = _run(
                store,
                apply=False,
                resolve_directory=lambda d: "widget-domain" if "widget" in d else "",
            )
            assert result["filled"] == 1
            with store.batch_pool.connection() as conn:
                row = _fetch_row(conn, memory_id)
            assert row["domain"] == ""  # unchanged — dry run
        finally:
            with store.batch_pool.connection() as conn:
                conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
                conn.commit()
