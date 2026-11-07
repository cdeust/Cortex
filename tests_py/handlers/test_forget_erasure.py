"""A hard ``forget`` erases every copy of the memory (audit 2026-10-21, E15).

The audit found the hard-delete path leaving the full original text in
``memory_archives``, while PRIVACY.md promised removal "across every
substrate". Each test below writes one unique marker through the real write
paths that copy a memory's text (the memory row and its FTS/vector index, a
compression archive, wiki claim, draft, citation and compiled page, a
prospective trigger and a rule mined from it, an extracted entity, a promoted
wiki page file), hard-forgets the memory through the ``forget`` handler, then
searches the whole database (every text column of every table, found in the
catalog at run time) and the wiki tree for the marker. On SQLite the database
file itself (and its WAL) is searched byte by byte.

The fixture uses only APIs that exist on ``main``, so the same tests show the
pre-fix behaviour (they fail there).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py._db_text_scan import locations
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

# unique per run: a copy left in a shared test database by an earlier run (or
# by the pre-fix code) can never satisfy or break this run's assertions
RUN = uuid.uuid4().hex[:12]
MARKER = f"ERASE-ME-{RUN} personal record of Jane Placeholder{RUN}"
KEEP = f"KEEP-ME-{RUN} unrelated memory"
DOMAIN = "forget-erasure-test"


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path, monkeypatch):
    from mcp_server.handlers import forget

    if request.param == "sqlite":
        s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    else:
        if not _USE_PG:
            pytest.skip("PostgreSQL test database not reachable")
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        s = PgMemoryStore()
    monkeypatch.setattr(forget, "_store", s)
    yield s
    s.close()


def _seed(store, wiki_root: Path) -> int:
    """Write MARKER through every path that copies a memory's text."""
    mid = store.insert_memory({"content": MARKER, "tags": ["t"], "domain": DOMAIN})
    keep = store.insert_memory({"content": KEEP, "tags": ["t"], "domain": DOMAIN})
    # compression: the original goes to the archive, the row keeps a summary
    store.insert_archive(
        {
            "original_memory_id": mid,
            "content": MARKER,
            "embedding": None,
            "archive_reason": "compression",
        }
    )
    store.update_memory_compression(mid, "summary", None, 1, original_content=MARKER)
    _seed_entities(store, mid, keep)
    _seed_mined(store, mid)
    _seed_wiki(store, mid, wiki_root)
    return mid


def _seed_entities(store, mid: int, keep: int) -> None:
    def entity(name: str, kind: str, **extra) -> int:
        return store.insert_entity(
            {"name": name, "type": kind, "domain": DOMAIN, **extra}
        )

    store.insert_memory_entity(mid, entity(f"Jane Placeholder{RUN}", "person"))
    shared = entity(f"SharedConcept{RUN}", "concept")
    store.insert_memory_entity(mid, shared)
    store.insert_memory_entity(keep, shared)
    symbol = entity(f"parse_config{RUN}", "function", origin="ast_symbol")
    store.insert_memory_entity(mid, symbol)


def _seed_mined(store, mid: int) -> None:
    store.insert_prospective_memory(
        {
            "content": f"remind: {MARKER}",
            "trigger_condition": "deploy",
            "trigger_type": "keyword",
            "source_memory_id": mid,
        }
    )
    store.insert_rule(
        {
            "condition": f"content contains {MARKER}",
            "action": "boost:0.1",
            "source_memory_id": mid,
        }
    )


def _seed_wiki(store, mid: int, wiki_root: Path) -> None:
    from mcp_server.infrastructure.pg_store_wiki_claims import insert_claim_events
    from mcp_server.infrastructure.pg_store_wiki_drafts import insert_draft
    from mcp_server.infrastructure.pg_store_wiki_notes import insert_citation
    from mcp_server.infrastructure.pg_store_wiki_pages import upsert_page

    conn = store._conn
    insert_claim_events(conn, [{"memory_id": mid, "text": f"claim: {MARKER}"}])
    insert_draft(
        conn,
        {"memory_id": mid, "title": f"draft {MARKER}", "kind": "note", "lead": MARKER},
    )
    rel = f"notes/{DOMAIN}/{mid}-erase-me.md"
    page = {
        "rel_path": rel,
        "slug": "erase-me",
        "kind": "note",
        "body": MARKER,
        "title": f"page {MARKER}",
        "memory_id": mid,
        "domain": DOMAIN,
    }
    page_id, _ = upsert_page(conn, page)
    insert_citation(conn, page_id, domain=DOMAIN, memory_id=mid)
    conn.commit()
    path = wiki_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nmemory_id: {mid}\n---\n# page\n\n{MARKER}\n", encoding="utf-8"
    )


def _forget(mid: int) -> dict:
    from mcp_server.handlers.forget import handler

    return asyncio.run(handler({"memory_id": mid, "force": True}))


def test_hard_forget_leaves_the_text_in_no_table(store, tmp_path, monkeypatch):
    from mcp_server.handlers import forget

    monkeypatch.setattr(forget, "WIKI_ROOT", tmp_path / "wiki", raising=False)
    mid = _seed(store, tmp_path / "wiki")
    assert locations(store, MARKER) != []  # the fixture really wrote copies
    result = _forget(mid)
    assert result["deleted"] is True and result["method"] == "hard"
    assert result["complete"] is True and result["residue"] == []
    assert locations(store, MARKER) == []
    assert locations(store, f"Jane Placeholder{RUN}") == []  # orphaned extracted entity
    # what was not this memory's survives
    assert locations(store, KEEP) != []
    assert locations(store, f"SharedConcept{RUN}") != []
    assert locations(store, f"parse_config{RUN}") != []  # a code symbol is kept


def test_hard_forget_removes_the_page_files_derived_from_the_memory(
    store, tmp_path, monkeypatch
):
    from mcp_server.handlers import forget

    monkeypatch.setattr(forget, "WIKI_ROOT", tmp_path / "wiki", raising=False)
    mid = _seed(store, tmp_path / "wiki")
    _forget(mid)
    for path in (tmp_path / "wiki").rglob("*"):
        if path.is_file():
            assert MARKER not in path.read_text(encoding="utf-8", errors="replace"), (
                path
            )


def test_sqlite_file_and_wal_hold_no_byte_of_the_text(tmp_path, monkeypatch):
    from mcp_server.handlers import forget

    store = SqliteMemoryStore(str(tmp_path / "memory.db"))
    monkeypatch.setattr(forget, "_store", store)
    monkeypatch.setattr(forget, "WIKI_ROOT", tmp_path / "wiki", raising=False)
    try:
        mid = _seed(store, tmp_path / "wiki")
        on_disk = b"".join(
            (tmp_path / n).read_bytes()
            for n in ("memory.db", "memory.db-wal")
            if (tmp_path / n).exists()
        )
        assert f"ERASE-ME-{RUN}".encode() in on_disk  # the fixture really wrote bytes
        assert _forget(mid)["wal_truncated"] is True
        for name in ("memory.db", "memory.db-wal"):
            path = tmp_path / name
            if path.exists():
                assert f"ERASE-ME-{RUN}".encode() not in path.read_bytes(), name
    finally:
        store.close()


def test_soft_forget_keeps_the_content_by_design(store, tmp_path, monkeypatch):
    from mcp_server.handlers.forget import handler

    mid = store.insert_memory({"content": MARKER, "tags": [], "domain": DOMAIN})
    result = asyncio.run(handler({"memory_id": mid, "soft": True}))
    assert result["method"] == "soft"
    assert locations(store, MARKER) != []


def test_a_failing_step_erases_nothing_and_raises(store, tmp_path, monkeypatch):
    """No partial erasure: the old handler logged a failed claim deletion and
    went on deleting the row; now any failing statement rolls back all."""
    from mcp_server.handlers import forget
    from mcp_server.infrastructure import memory_erasure

    monkeypatch.setattr(forget, "WIKI_ROOT", tmp_path / "wiki", raising=False)
    mid = _seed(store, tmp_path / "wiki")
    broken = (
        *memory_erasure.DERIVED_ROWS,
        ("boom", "DELETE FROM no_such_table WHERE id = %s"),
    )
    monkeypatch.setattr(memory_erasure, "DERIVED_ROWS", broken)
    with pytest.raises(Exception, match="no_such_table"):
        _forget(mid)
    assert store.get_memory(mid) is not None
    assert ("memory_archives", "content") in [
        (t.split(".")[-1], c) for t, c in locations(store, MARKER)
    ]


def test_a_reader_blocking_the_wal_truncation_is_reported(tmp_path, monkeypatch):
    """Another connection's open snapshot keeps old WAL frames; the result says
    so instead of claiming the bytes are gone."""
    import sqlite3

    from mcp_server.handlers import forget

    store = SqliteMemoryStore(str(tmp_path / "memory.db"))
    monkeypatch.setattr(forget, "_store", store)
    monkeypatch.setattr(forget, "WIKI_ROOT", tmp_path / "wiki", raising=False)
    reader = sqlite3.connect(str(tmp_path / "memory.db"))
    try:
        mid = _seed(store, tmp_path / "wiki")
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM memories").fetchone()
        result = _forget(mid)
        assert result["deleted"] is True
        assert result["wal_truncated"] is False
    finally:
        reader.close()
        store.close()
