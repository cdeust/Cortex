"""Hard forget with a failing step, by fault injection (review of PR #775, N4).

Before the commit a failure rolls everything back and is raised; after it
(WAL truncation, page files, artifact) the memory is gone and the failure is
reported as residue with ``complete: False``.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.handlers.test_forget_erasure import MARKER, _forget, _seed


def _sqlite_forget_store(tmp_path, monkeypatch) -> SqliteMemoryStore:
    from mcp_server.handlers import forget

    store = SqliteMemoryStore(str(tmp_path / "memory.db"))
    monkeypatch.setattr(forget, "_store", store)
    monkeypatch.setattr(forget, "WIKI_ROOT", tmp_path / "wiki", raising=False)
    return store


def test_a_failing_fts_purge_erases_nothing_and_raises(tmp_path, monkeypatch):
    """Review of #775, N4: the FTS optimize merge ran after the commit, so a
    failure raised although the rows were already gone. It now runs inside
    the transaction: a failure rolls everything back."""
    import sqlite3

    from mcp_server.infrastructure import sqlite_store_erasure

    def broken_purge(self, secure):
        raise sqlite3.OperationalError("injected: optimize failed")

    store = _sqlite_forget_store(tmp_path, monkeypatch)
    try:
        mid = _seed(store, tmp_path / "wiki")
        monkeypatch.setattr(
            sqlite_store_erasure.SqliteErasureMixin, "_purge_fts", broken_purge
        )
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            _forget(mid)
        assert store.get_memory(mid) is not None
    finally:
        store.close()


@pytest.mark.parametrize("step", ["wal", "pages", "artifact"])
def test_a_failing_step_after_the_commit_is_reported(tmp_path, monkeypatch, step):
    """Review of #775, N4: once the rows are committed the memory is gone; a
    later step (WAL truncation, page files, artifact) that fails is reported
    as residue, not raised as if nothing had been erased."""
    import sqlite3

    from mcp_server.handlers import forget
    from mcp_server.infrastructure import sqlite_store_erasure

    def fail(*_args, **_kwargs):
        raise (sqlite3.OperationalError if step == "wal" else OSError)("injected")

    store = _sqlite_forget_store(tmp_path, monkeypatch)
    try:
        mid = _seed(store, tmp_path / "wiki")
        target = {
            "wal": (sqlite_store_erasure.SqliteErasureMixin, "_truncate_wal"),
            "pages": (forget, "remove_derived_pages"),
            "artifact": (forget, "delete_artifact_if_unreferenced"),
        }[step]
        monkeypatch.setattr(*target, fail)
        if step == "artifact":
            from mcp_server.core.gist_extraction import format_artifact_pointer

            pointer = format_artifact_pointer(str(tmp_path / "a.md"), 10)
            store.update_memory_compression(
                mid, "summary", None, 1, original_content=f"{MARKER}\n{pointer}"
            )
        result = _forget(mid)
        assert result["deleted"] is True
        assert store.get_memory(mid) is None
        assert result["complete"] is False, result
        assert any("injected" in r["error"] for r in result["residue"]), result
    finally:
        store.close()
