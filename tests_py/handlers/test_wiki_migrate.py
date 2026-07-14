"""Tests for wiki_migrate's ghost-reconciliation purge phase.

Covers:
  1. ``find_ghost_rel_paths`` — pure set-difference, no I/O.
  2. ``pg_store_wiki_pages.list_all_rel_paths`` / ``delete_pages_by_rel_path``
     — SQL shape via a mocked cursor (unit tier, matches
     test_wiki_page_sources.py's convention: no live Postgres required).
  3. ``purge_ghost_pages`` — dry_run gate (report vs actually delete).
  4. ``migrate_wiki`` end-to-end parity: after migrate+purge on a real
     tmp_path filesystem, the number of "PG rows" tracked by an in-memory
     fake store equals the number of FS-eligible pages — the literal
     COUNT(wiki.pages) == FS-eligible-page-count claim, exercised without
     a live database. A separate live proof against a throwaway Postgres
     database (created and dropped, never the shared dev/prod DB) is
     reported in the task output; this module is the CI-safe unit tier.

The `_`-prefixed kind dirs and root README.md are outside PAGE_KINDS'
scan entirely (verified against mcp_server.core.wiki_layout.PAGE_KINDS),
so they never appear as candidates in either the upsert or the purge
phase — no dedicated exclusion-list test is needed; ``list_pages`` (used
by both phases) already enforces it structurally.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_server.handlers.wiki_migrate import (
    _normalize_status,
    page_row_from_md,
    find_ghost_rel_paths,
    migrate_wiki,
    purge_ghost_pages,
)
from mcp_server.infrastructure.pg_store_wiki_pages import (
    delete_pages_by_rel_path,
    list_all_rel_paths,
)


# ── find_ghost_rel_paths — pure set difference ──────────────────────────


def test_ghost_rel_paths_finds_pg_only_entries() -> None:
    fs = ["notes/alive.md", "adr/1-foo.md"]
    pg = ["notes/alive.md", "adr/1-foo.md", "notes/deleted.md"]
    assert find_ghost_rel_paths(fs, pg) == ["notes/deleted.md"]


def test_ghost_rel_paths_empty_when_fs_and_pg_match() -> None:
    fs = ["notes/alive.md"]
    pg = ["notes/alive.md"]
    assert find_ghost_rel_paths(fs, pg) == []


def test_ghost_rel_paths_not_yet_migrated_is_not_a_ghost() -> None:
    """A page on the FS but not yet in PG is not-yet-migrated, not a ghost."""
    fs = ["notes/brand-new.md"]
    pg: list[str] = []
    assert find_ghost_rel_paths(fs, pg) == []


def test_ghost_rel_paths_result_is_sorted() -> None:
    fs: list[str] = []
    pg = ["notes/z.md", "notes/a.md"]
    assert find_ghost_rel_paths(fs, pg) == ["notes/a.md", "notes/z.md"]


# ── _normalize_status / page_row_from_md status validation ─────────────
# Mirrors wiki.pages.status's DB CHECK constraint (pg_schema.py) — every
# value accepted here must also be accepted there, and vice versa.


def test_normalize_status_accepts_adr_status() -> None:
    status, warning = _normalize_status("proposed", "adr/cortex/1-foo.md")
    assert status == "proposed"
    assert warning is None


def test_normalize_status_accepts_specs_status() -> None:
    status, warning = _normalize_status("implemented", "specs/cortex/1-foo.md")
    assert status == "implemented"
    assert warning is None


def test_normalize_status_accepts_legacy_maturity_and_living() -> None:
    for value in ("seedling", "budding", "evergreen", "living"):
        status, warning = _normalize_status(value, "notes/cortex/1-foo.md")
        assert status == value
        assert warning is None


def test_normalize_status_unknown_falls_back_to_seedling_with_warning() -> None:
    status, warning = _normalize_status("garbage", "notes/cortex/1-foo.md")
    assert status == "seedling"
    assert (
        warning
        == "notes/cortex/1-foo.md: unknown status 'garbage' -> falling back to 'seedling'"
    )


def testpage_row_from_md_valid_adr_status_passes_through_unwarned() -> None:
    content = "---\ntitle: Some ADR\nkind: adr\ndomain: cortex\nstatus: accepted\n---\n\nBody.\n"
    row = page_row_from_md("adr/cortex/1-some-adr.md", content)
    assert row["status"] == "accepted"
    assert row["status_warning"] is None


def testpage_row_from_md_unknown_status_falls_back_and_warns() -> None:
    content = "---\ntitle: Some Note\nkind: notes\ndomain: cortex\nstatus: garbage\n---\n\nBody.\n"
    row = page_row_from_md("notes/cortex/1-some-note.md", content)
    assert row["status"] == "seedling"
    assert row["status_warning"] == (
        "notes/cortex/1-some-note.md: unknown status 'garbage' -> falling back to 'seedling'"
    )


# ── pg_store_wiki_pages: list_all_rel_paths / delete_pages_by_rel_path ──


def _mock_conn() -> MagicMock:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


def test_list_all_rel_paths_queries_wiki_pages() -> None:
    conn = _mock_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [{"rel_path": "notes/a.md"}, {"rel_path": "adr/1-b.md"}]

    result = list_all_rel_paths(conn)

    assert result == ["notes/a.md", "adr/1-b.md"]
    cur.execute.assert_called_once_with("SELECT rel_path FROM wiki.pages")


def test_list_all_rel_paths_handles_tuple_rows() -> None:
    """Defensive: row_factory may not be dict_row depending on caller."""
    conn = _mock_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [("notes/a.md",)]

    assert list_all_rel_paths(conn) == ["notes/a.md"]


def test_delete_pages_by_rel_path_empty_list_is_a_noop() -> None:
    conn = _mock_conn()
    result = delete_pages_by_rel_path(conn, [])
    assert result == []
    conn.cursor.assert_not_called()


def test_delete_pages_by_rel_path_issues_delete_returning() -> None:
    conn = _mock_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [{"id": 5, "rel_path": "notes/deleted.md"}]

    result = delete_pages_by_rel_path(conn, ["notes/deleted.md"])

    assert result == [{"id": 5, "rel_path": "notes/deleted.md"}]
    executed_sql, executed_params = cur.execute.call_args.args
    assert "DELETE FROM wiki.pages" in executed_sql
    assert "RETURNING id, rel_path" in executed_sql
    assert executed_params == (["notes/deleted.md"],)


# ── purge_ghost_pages — dry_run gate ─────────────────────────────────────


def test_purge_ghost_pages_dry_run_reports_without_deleting(monkeypatch) -> None:
    conn = object()  # unused by the monkeypatched store calls below
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.list_all_rel_paths",
        lambda _conn: ["notes/alive.md", "notes/ghost.md"],
    )
    delete_calls: list[list[str]] = []
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.delete_pages_by_rel_path",
        lambda _conn, rel_paths: delete_calls.append(list(rel_paths)) or [],
    )

    result = purge_ghost_pages(conn, ["notes/alive.md"], dry_run=True)

    assert result == {
        "dry_run": True,
        "ghost_count": 1,
        "ghost_paths": ["notes/ghost.md"],
        "purged": [],
    }
    assert delete_calls == []  # dry_run must never call the store delete


def test_purge_ghost_pages_real_run_deletes_and_reports(monkeypatch) -> None:
    conn = object()
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.list_all_rel_paths",
        lambda _conn: ["notes/alive.md", "notes/ghost.md"],
    )
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.delete_pages_by_rel_path",
        lambda _conn, rel_paths: [{"id": 1, "rel_path": rp} for rp in rel_paths],
    )

    result = purge_ghost_pages(conn, ["notes/alive.md"], dry_run=False)

    assert result == {
        "dry_run": False,
        "ghost_count": 1,
        "ghost_paths": ["notes/ghost.md"],
        "purged": ["notes/ghost.md"],
    }


def test_purge_ghost_pages_no_ghosts_never_calls_delete(monkeypatch) -> None:
    conn = object()
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.list_all_rel_paths",
        lambda _conn: ["notes/alive.md"],
    )
    delete_called = []
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.delete_pages_by_rel_path",
        lambda _conn, rel_paths: delete_called.append(rel_paths) or [],
    )

    result = purge_ghost_pages(conn, ["notes/alive.md"], dry_run=False)

    assert result["ghost_count"] == 0
    assert delete_called == []


# ── migrate_wiki end-to-end parity (fake in-memory store) ───────────────


class _FakePagesStore:
    """Minimal in-memory stand-in for wiki.pages, keyed on rel_path.

    Mirrors the real upsert_page/list_all_rel_paths/delete_pages_by_rel_path
    contract closely enough to prove migrate_wiki's orchestration end to
    end without a live Postgres connection. The genuine SQL/cascade
    behavior (wiki.links, wiki.page_sources, wiki.citations all cascading
    on DELETE FROM wiki.pages) was proven separately on a throwaway
    Postgres database (created via `createdb`, dropped after — see task
    output); this fake only needs to track rel_path membership to verify
    the COUNT-parity claim at the orchestration level.
    """

    def __init__(self) -> None:
        self.rows: dict[str, int] = {}
        self._next_id = 1

    def upsert(self, row: dict) -> tuple[int, bool]:
        rel = row["rel_path"]
        if rel in self.rows:
            return self.rows[rel], False
        page_id = self._next_id
        self._next_id += 1
        self.rows[rel] = page_id
        return page_id, True

    def list_all_rel_paths(self) -> list[str]:
        return list(self.rows.keys())

    def delete_by_rel_path(self, rel_paths: list[str]) -> list[dict]:
        deleted = []
        for rp in rel_paths:
            page_id = self.rows.pop(rp, None)
            if page_id is not None:
                deleted.append({"id": page_id, "rel_path": rp})
        return deleted


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakePagesStore()
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.upsert_page",
        lambda _conn, row: store.upsert(row),
    )
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.list_all_rel_paths",
        lambda _conn: store.list_all_rel_paths(),
    )
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.delete_pages_by_rel_path",
        lambda _conn, rel_paths: store.delete_by_rel_path(rel_paths),
    )
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.delete_links_from",
        lambda _conn, _page_id: 0,
    )
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.upsert_link",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate.resolve_unresolved_links",
        lambda _conn: 0,
    )
    monkeypatch.setattr(
        "mcp_server.handlers.wiki_migrate._existing_memory_ids",
        lambda _conn, ids: set(),
    )
    return store


def _write_page(tmp_path, rel_path: str, title: str) -> None:
    full = tmp_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        f"---\ntitle: {title}\nkind: notes\ndomain: cortex\n---\n\n# {title}\n"
    )


def test_migrate_wiki_parity_after_purge(tmp_path, fake_store) -> None:
    """After migrate+purge, the fake store's row count == FS-eligible pages.

    Scenario: 2 pages on disk, plus 1 pre-existing "ghost" row in the
    store (simulating a page that used to exist but was deleted/renamed
    off the FS, e.g. by wiki_purge). dry_run=False must purge the ghost.
    """
    _write_page(tmp_path, "notes/alive-page.md", "Alive Page")
    _write_page(tmp_path, "notes/second-alive.md", "Second Alive")
    fake_store.rows["notes/deleted-page.md"] = 999  # pre-existing ghost

    summary = migrate_wiki(tmp_path, conn=MagicMock(), dry_run=False)

    assert summary["pages_processed"] == 2
    assert summary["purge"]["ghost_count"] == 1
    assert summary["purge"]["ghost_paths"] == ["notes/deleted-page.md"]
    assert summary["purge"]["purged"] == ["notes/deleted-page.md"]
    assert len(fake_store.rows) == 2
    assert set(fake_store.rows.keys()) == {
        "notes/alive-page.md",
        "notes/second-alive.md",
    }


def test_migrate_wiki_reports_status_warning_without_failing_the_page(
    tmp_path, fake_store
) -> None:
    """A garbage frontmatter status is a non-blocking warning, not an error."""
    full = tmp_path / "notes/cortex/garbage-status.md"
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(
        "---\ntitle: Garbage\nkind: notes\ndomain: cortex\nstatus: garbage\n---\n\nBody.\n"
    )

    summary = migrate_wiki(tmp_path, conn=MagicMock(), dry_run=True)

    assert summary["error_count"] == 0
    assert summary["warning_count"] == 1
    assert summary["warnings"] == [
        "notes/cortex/garbage-status.md: unknown status 'garbage' -> falling back to 'seedling'"
    ]
    assert "notes/cortex/garbage-status.md" in fake_store.rows


def test_migrate_wiki_dry_run_default_leaves_ghost_in_place(
    tmp_path, fake_store
) -> None:
    _write_page(tmp_path, "notes/alive-page.md", "Alive Page")
    fake_store.rows["notes/deleted-page.md"] = 999

    summary = migrate_wiki(tmp_path, conn=MagicMock())  # dry_run defaults to True

    assert summary["purge"]["dry_run"] is True
    assert summary["purge"]["ghost_count"] == 1
    assert summary["purge"]["purged"] == []
    # Ghost row is still present — dry_run never deletes.
    assert "notes/deleted-page.md" in fake_store.rows


# ── issue #105 — dry_run must be transactionally neutral end-to-end ────
#
# Regression: `migrate_wiki` used to call `conn.commit()` unconditionally
# after all four passes, so passes 1-3 (upsert_page, delete_links_from /
# upsert_link, resolve_unresolved_links) were persisted even when
# dry_run=True — only pass 4 (purge_ghost_pages) had its own dry_run gate.
# `--dry-run` must never leave a durable write behind on ANY pass.


def test_migrate_wiki_dry_run_rolls_back_never_commits(tmp_path, fake_store) -> None:
    """dry_run=True must roll back the connection, never commit it.

    This is the mechanism-level proof: on the code prior to the fix,
    `conn.commit()` was called unconditionally (this assertion fails
    against that code — `commit.assert_not_called()` raises). After the
    fix, dry_run rolls back so passes 1-3's writes are discarded along
    with pass 4's.
    """
    _write_page(tmp_path, "notes/alive-page.md", "Alive Page")
    conn = MagicMock()

    migrate_wiki(tmp_path, conn=conn, dry_run=True)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_migrate_wiki_real_run_commits_never_rolls_back(tmp_path, fake_store) -> None:
    """dry_run=False must commit — the mirror-image proof to the above."""
    _write_page(tmp_path, "notes/alive-page.md", "Alive Page")
    conn = MagicMock()

    migrate_wiki(tmp_path, conn=conn, dry_run=False)

    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
