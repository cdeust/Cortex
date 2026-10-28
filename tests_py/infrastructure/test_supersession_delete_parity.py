"""Deletion preserves surviving versions on both stores (issue #699).

source: ADR-9852; PostgreSQL's existing ON DELETE SET NULL contract.
The unit CI provisions PostgreSQL; the SQLite leg always runs.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.conftest import _USE_PG

_DOMAIN = "supersession-delete-parity"


@pytest.fixture(params=["sqlite", "pg"])
def store(request):
    if request.param == "pg":
        if not _USE_PG:
            pytest.skip("PostgreSQL unavailable; unit CI provisions it")
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        backend = PgMemoryStore()
    else:
        backend = SqliteMemoryStore()
    try:
        yield backend
    finally:
        if request.param == "pg":
            backend._conn.execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
            backend._conn.commit()
        backend.close()


def _version(content):
    return {"content": content, "domain": _DOMAIN, "source": "user"}


def _pair(store):
    old = store.insert_memory(_version("previous version"))
    head, target = store.supersede_atomic(_version("replacement version"), old)
    assert head is not None and target == old
    return old, head


def _heads(store):
    return {row["id"] for row in store.get_memories_for_domain(_DOMAIN, min_heat=0.0)}


def test_deleting_head_restores_predecessor(store):
    old, head = _pair(store)
    assert _heads(store) == {head}
    assert store.delete_memory(head)
    assert store.get_memory(head) is None
    assert store.get_memory(old)["superseded_by_id"] is None
    assert _heads(store) == {old}
    assert not store.delete_memory(head)


def test_deleting_middle_clears_both_links_without_reconnecting(store):
    old, middle = _pair(store)
    head, target = store.supersede_atomic(_version("latest version"), middle)
    assert head is not None and target == middle
    assert store.delete_memory(middle)
    assert store.get_memory(old)["superseded_by_id"] is None
    assert store.get_memory(head)["supersedes_id"] is None
    assert _heads(store) == {old, head}


def test_deleting_tail_preserves_the_current_head(store):
    old, head = _pair(store)
    assert store.delete_memory(old)
    assert store.get_memory(head)["supersedes_id"] is None
    assert _heads(store) == {head}


def test_erasing_head_restores_predecessor(store):
    old, head = _pair(store)
    assert store.erase_memory(head).deleted
    assert store.get_memory(head) is None
    assert store.get_memory(old)["superseded_by_id"] is None
    assert _heads(store) == {old}


def test_delete_rolls_back_the_link_changes(store):
    old, head = _pair(store)
    store._conn.execute("BEGIN")
    store._conn.execute("DELETE FROM memories WHERE id = %s", (head,))
    assert store.get_memory(old)["superseded_by_id"] is None
    assert _heads(store) == {old}
    store._conn.rollback()
    assert store.get_memory(old)["superseded_by_id"] == head
    assert _heads(store) == {head}


def test_deleting_shared_head_restores_every_predecessor(store):
    old, head = _pair(store)
    other = store.insert_memory(_version("another predecessor"))
    store._conn.execute(
        "UPDATE memories SET superseded_by_id = %s WHERE id = %s",
        (head, other),
    )
    store._conn.commit()
    assert store.delete_memory(head)
    assert _heads(store) == {old, other}


def test_deleting_unrelated_memory_preserves_valid_links(store):
    old, head = _pair(store)
    unrelated = store.insert_memory(_version("unrelated version"))
    assert store.delete_memory(unrelated)
    assert store.get_memory(old)["superseded_by_id"] == head
    assert store.get_memory(head)["supersedes_id"] == old
    assert _heads(store) == {head}


def test_reopening_sqlite_repairs_legacy_links_and_preserves_valid_edges(tmp_path):
    path = str(tmp_path / "legacy.db")
    backend = SqliteMemoryStore(path)
    old, missing = _pair(backend)
    valid_old = backend.insert_memory(_version("valid old"))
    valid_head, _ = backend.supersede_atomic(_version("valid head"), valid_old)
    orphan_backlink = backend.insert_memory(_version("orphan backlink"))
    # Recreate a pre-fix database, bypassing any installed delete trigger.
    backend._conn.execute("DROP TRIGGER IF EXISTS trg_memories_supersession_delete")
    backend._conn.execute("DELETE FROM memories_fts WHERE rowid = %s", (missing,))
    backend._conn.execute("DELETE FROM memories WHERE id = %s", (missing,))
    backend._conn.execute(
        "UPDATE memories SET supersedes_id = %s WHERE id = %s",
        (missing, orphan_backlink),
    )
    backend._conn.commit()
    assert _heads(backend) == {valid_head, orphan_backlink}
    backend.close()

    # A second reopen proves the repair is idempotent.
    for _ in ("first reopen", "second reopen"):
        backend = SqliteMemoryStore(path)
        try:
            assert backend.get_memory(old)["superseded_by_id"] is None
            assert backend.get_memory(orphan_backlink)["supersedes_id"] is None
            assert backend.get_memory(valid_old)["superseded_by_id"] == valid_head
            assert backend.get_memory(valid_head)["supersedes_id"] == valid_old
            assert _heads(backend) == {old, valid_head, orphan_backlink}
        finally:
            backend.close()
