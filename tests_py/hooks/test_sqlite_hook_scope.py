"""Project-scoping tests for the SQLite hook paths (issue #604).

Split out of test_sqlite_hook_paths.py (craftsmanship file-size cap) along
the seam the ``*Scope`` classes already drew: this file owns every test
that exercises the project predicate itself, on a real SqliteMemoryStore
in tmp_path. test_sqlite_hook_paths.py keeps the tag/limit/FTS logic that
is orthogonal to scoping.

The starvation tests below are the review's required regression: the
predicate must run inside the store query, before its own LIMIT, so a
project's own row is not crowded out of the candidate pool by foreign
rows that rank higher on heat -- a post-fetch filter over an
already-truncated pool cannot satisfy this (it is exactly the bug fixed
after 7f27b418).
"""

from __future__ import annotations

import pytest

from mcp_server.hooks import auto_recall, session_start
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture()
def store(tmp_path):
    s = SqliteMemoryStore(db_path=str(tmp_path / "memory.db"))
    yield s
    s.close()


class TestPartitionBannerRowsScope:
    """issue #604: rows outside the session's project must not be injected."""

    def test_drops_other_project_keeps_global_and_ancestor(self):
        rows = [
            {
                "id": 1,
                "content": "other project",
                "tags": [],
                "heat": 0.9,
                "is_global": False,
                "directory_context": "/other/project",
            },
            {
                "id": 2,
                "content": "global",
                "tags": [],
                "heat": 0.9,
                "is_global": True,
                "directory_context": "",
            },
            {
                "id": 3,
                "content": "ancestor of session cwd",
                "tags": [],
                "heat": 0.9,
                "is_global": False,
                "directory_context": "/repo",
            },
            {
                "id": 4,
                "content": "empty directory_context is not a wildcard",
                "tags": [],
                "heat": 0.9,
                "is_global": False,
                "directory_context": "",
            },
        ]
        _, hot = session_start._partition_banner_rows(rows, "/repo/subdir")
        assert [m["id"] for m in hot] == [2, 3]


class TestRecallMemoriesSqliteScope:
    """issue #604: memories outside the session's project must not surface."""

    def test_drops_other_project_keeps_global_and_ancestor(self, store):
        store.insert_memory(
            {
                "content": "scopeword belongs to another project",
                "heat": 0.9,
                "directory_context": "/other/project",
            }
        )
        store.insert_memory(
            {
                "content": "scopeword is a global decision",
                "heat": 0.9,
                "is_global": True,
                "directory_context": "",
            }
        )
        store.insert_memory(
            {
                "content": "scopeword lives at an ancestor of the session cwd",
                "heat": 0.9,
                "directory_context": "/repo",
            }
        )
        store.insert_memory(
            {
                "content": "scopeword has an empty directory_context",
                "heat": 0.9,
                "directory_context": "",
            }
        )

        results = auto_recall._recall_memories_sqlite(
            store, "scopeword", "/repo/subdir"
        )

        contents = {m["content"] for m in results}
        assert "scopeword belongs to another project" not in contents
        assert "scopeword has an empty directory_context" not in contents
        assert "scopeword is a global decision" in contents
        assert "scopeword lives at an ancestor of the session cwd" in contents


def test_process_event_sqlite_without_project_root_restricts_to_globals(
    store, monkeypatch, capsys
):
    """issue #604: no CLAUDE_PROJECT_ROOT and no event cwd -> globals only,
    never everything, and the hook says so on stderr."""
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    store.insert_memory(
        {
            "content": "the deploy script is resumable by design",
            "heat": 0.9,
            "directory_context": "/repo",
        }
    )
    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.get_shared_store", lambda: store
    )

    with pytest.raises(SystemExit) as exc:
        auto_recall._process_event_sqlite(
            {"transcript_path": "/tmp/session-xyz.jsonl"},
            "why is the deploy script resumable",
        )

    assert exc.value.code == 0
    out, err = capsys.readouterr()
    assert "resumable" not in out
    assert "project root unresolved" in err


# ── Starvation: the project's own row must survive a foreign-heavy pool ──

# source: auto_recall._MAX_MEMORIES + 2 and session_start._HOT_LIMIT +
# _ANCHOR_LIMIT -- comfortably above both hooks' LIMIT windows.
_FOREIGN_ROW_COUNT = 25


def _seed_starvation_store(store) -> None:
    """One in-project row at moderate heat, outranked on heat by more
    foreign rows than any of the hooks' LIMIT windows allow through."""
    store.insert_memory(
        {
            "content": "scopeword the project's own decision",
            "heat": 0.5,
            "directory_context": "/repo",
        }
    )
    for i in range(_FOREIGN_ROW_COUNT):
        store.insert_memory(
            {
                "content": f"scopeword foreign row {i}",
                "heat": 0.99,
                "directory_context": f"/other/project-{i}",
            }
        )


def test_recall_memories_sqlite_survives_a_foreign_heavy_pool(store):
    _seed_starvation_store(store)

    results = auto_recall._recall_memories_sqlite(store, "scopeword", "/repo/subdir")

    contents = [m["content"] for m in results]
    assert any("the project's own decision" in c for c in contents), (
        f"in-project row starved out by foreign rows above the heat floor: {contents}"
    )
    assert all("foreign row" not in c for c in contents)


def test_sqlite_context_survives_a_foreign_heavy_pool(store, monkeypatch, capsys):
    """End-to-end through _sqlite_context, exercising the same wiring a
    real SessionStart event would: get_hot_memories called with the
    project's directory_ancestors, not filtered after the fact."""
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.get_shared_store", lambda: store
    )
    monkeypatch.setattr(session_start, "_print_external_sources", lambda: None)
    _seed_starvation_store(store)

    session_start._sqlite_context(
        {"transcript_path": "/tmp/session-starve.jsonl", "cwd": "/repo/subdir"}
    )

    out = capsys.readouterr().out
    assert "the project's own decision" in out, (
        f"in-project row starved out by foreign rows above the heat floor: {out!r}"
    )
    assert "foreign row" not in out
