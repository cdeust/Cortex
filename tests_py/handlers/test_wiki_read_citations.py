"""T2-H4/INC5.4 (D7): wiki_read's citation write-path side effect.

Exercises ``_cite_page`` / ``_resolve_session_id`` wiring in isolation
via fakes that faithfully reproduce the contracts of the collaborators
they replace:

- ``current_window_session`` — T2-D12: session id or None, never raises
  by its own documented contract (belt-and-suspenders tested here too).
- ``get_page_by_rel_path`` — PG lookup, None when the page was never
  compiled into wiki.pages.
- ``insert_citation`` — DB-level dedup on (page_id, session_id) via the
  partial unique index ``uq_wiki_citations_page_session`` (session_id
  must be non-empty to dedup); returns None on a duplicate insert, an
  id on a new row. The fake below reproduces exactly that semantics so
  the handler-level call-count assertions are meaningful.

Live-DB proof of the actual trigger/index behavior is a separate,
non-pytest verification step (see engineer's final report).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.core.wiki_identity import generate_page_id
from mcp_server.handlers import wiki_read
from tests_py._store_call import FakeConnStore, mark_test_operation


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _page_md(page_id: str, title: str, body: str = "Body.") -> str:
    return (
        f"---\nid: {page_id}\ntitle: {title}\nkind: explanation\n"
        f"lifecycle: seedling\naudience:\n  - developer\n"
        f"provenance: human\n---\n\n# {title}\n\n{body}\n"
    )


@pytest.fixture
def tmp_wiki(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wiki_read, "WIKI_ROOT", str(tmp_path))
    return tmp_path


class _FakeConn:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.committed = False


class _FakeStore(FakeConnStore):
    """PostgreSQL-shaped store lending ``conn``; the page and citation
    operations are monkeypatched with marked doubles (ADR-1112 increment 2)."""


class _FakeCitations:
    """Reproduces the (page_id, session_id) partial-unique-index dedup."""

    def __init__(self) -> None:
        self.rows: list[tuple[int, str, str, int | None]] = []
        self._next_id = 1

    def insert(
        self,
        conn,
        page_id: int,
        session_id: str = "",
        domain: str = "",
        memory_id: int | None = None,
    ) -> int | None:
        if session_id != "":
            for existing in self.rows:
                if existing[0] == page_id and existing[1] == session_id:
                    return None
        cid = self._next_id
        self._next_id += 1
        self.rows.append((page_id, session_id, domain, memory_id))
        return cid


@pytest.fixture
def wired_pg(monkeypatch):
    """Wire fake PG collaborators; return (citations_store, pages_by_path)."""
    conn = _FakeConn()
    store = _FakeStore(conn)
    citations = _FakeCitations()
    pages: dict[str, dict] = {}

    monkeypatch.setattr(wiki_read, "_get_store", lambda: store)
    monkeypatch.setattr(
        wiki_read,
        "get_page_by_rel_path",
        mark_test_operation(lambda _conn, rel_path: pages.get(rel_path)),
    )
    monkeypatch.setattr(
        wiki_read, "insert_citation", mark_test_operation(citations.insert)
    )
    return citations, pages


def _register_page(pages: dict, tmp_wiki: Path, rel_path: str, page_id: int) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / rel_path, _page_md(pid, rel_path))
    pages[rel_path] = {"id": page_id, "domain": "d", "memory_id": None}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── 1. Read with a resolvable session → 1 citation ─────────────────────


def test_read_with_session_records_one_citation(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    citations, pages = wired_pg
    _register_page(pages, tmp_wiki, "a.md", page_id=1)
    monkeypatch.setattr(wiki_read, "current_window_session", lambda: "sess-A")

    result = _run(wiki_read.handler({"path": "a.md"}))

    assert "error" not in result
    assert citations.rows == [(1, "sess-A", "d", None)]


# ── 2. Re-read in the SAME session → 0 new citations ────────────────────


def test_reread_same_session_dedups(tmp_wiki, wired_pg, monkeypatch) -> None:
    citations, pages = wired_pg
    _register_page(pages, tmp_wiki, "a.md", page_id=1)
    monkeypatch.setattr(wiki_read, "current_window_session", lambda: "sess-A")

    _run(wiki_read.handler({"path": "a.md"}))
    result = _run(wiki_read.handler({"path": "a.md"}))

    assert "error" not in result
    assert len(citations.rows) == 1


# ── 3. Read from a DIFFERENT session → 2nd citation ─────────────────────


def test_read_from_second_session_adds_citation(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    citations, pages = wired_pg
    _register_page(pages, tmp_wiki, "a.md", page_id=1)

    monkeypatch.setattr(wiki_read, "current_window_session", lambda: "sess-A")
    _run(wiki_read.handler({"path": "a.md"}))
    monkeypatch.setattr(wiki_read, "current_window_session", lambda: "sess-B")
    _run(wiki_read.handler({"path": "a.md"}))

    assert len(citations.rows) == 2
    assert {r[1] for r in citations.rows} == {"sess-A", "sess-B"}


# ── 4. No resolvable session → 0 citations, read still succeeds ────────


def test_no_session_records_no_citation(tmp_wiki, wired_pg, monkeypatch) -> None:
    citations, pages = wired_pg
    _register_page(pages, tmp_wiki, "a.md", page_id=1)
    monkeypatch.setattr(wiki_read, "current_window_session", lambda: None)

    result = _run(wiki_read.handler({"path": "a.md"}))

    assert "error" not in result
    assert citations.rows == []


# ── 5. Page never compiled into PG → 0 citations, read still succeeds ──


def test_page_absent_from_pg_records_no_citation(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    citations, pages = wired_pg
    # Filesystem page exists but is NOT registered in `pages` (never compiled).
    pid = generate_page_id()
    _write(tmp_wiki / "orphan.md", _page_md(pid, "orphan.md"))
    monkeypatch.setattr(wiki_read, "current_window_session", lambda: "sess-A")

    result = _run(wiki_read.handler({"path": "orphan.md"}))

    assert "error" not in result
    assert "content" in result
    assert citations.rows == []


# ── 6. PG unreachable → read still succeeds, no exception propagates ───


def test_pg_down_read_still_succeeds(tmp_wiki, monkeypatch) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "a.md", _page_md(pid, "a.md"))
    monkeypatch.setattr(wiki_read, "current_window_session", lambda: "sess-A")

    def _boom():
        raise RuntimeError("PG unreachable")

    monkeypatch.setattr(wiki_read, "_get_store", _boom)

    result = _run(wiki_read.handler({"path": "a.md"}))

    assert "error" not in result
    assert "content" in result


# ── Registry lookup itself raising is also swallowed (belt-and-suspenders) ─


def test_session_registry_exception_degrades_to_no_citation(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    citations, pages = wired_pg
    _register_page(pages, tmp_wiki, "a.md", page_id=1)

    def _boom():
        raise RuntimeError("registry read failed")

    monkeypatch.setattr(wiki_read, "current_window_session", _boom)

    result = _run(wiki_read.handler({"path": "a.md"}))

    assert "error" not in result
    assert citations.rows == []
