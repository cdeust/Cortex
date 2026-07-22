"""Tests for the hooks' SQLite backend paths (sqlite-first install).

The plugin's zero-config default provisions no PostgreSQL server, so the
two context-injecting hooks that previously spoke raw psycopg SQL —
session_start (banner) and auto_recall (per-prompt injection) — gained a
store-abstraction path activated when the resolved backend is sqlite
(mcp_server/infrastructure/backend_marker.effective_backend). These
tests exercise that path against a real SqliteMemoryStore in tmp_path —
no PostgreSQL, no network, no embedding model.
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


# ── backend gate ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("module", [session_start, auto_recall])
def test_backend_gate_follows_env(module, monkeypatch):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    assert module._backend_is_sqlite() is True
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
    assert module._backend_is_sqlite() is False


# ── session_start: banner partition ──────────────────────────────────────


class TestPartitionBannerRows:
    def test_noise_tags_excluded(self):
        rows = [
            {"id": 1, "content": "tool noise", "tags": ["auto-captured"], "heat": 0.9},
            {"id": 2, "content": "replica", "tags": ["memory-replica"], "heat": 0.9},
            {"id": 3, "content": "real", "tags": [], "heat": 0.8},
        ]
        anchors, hot = session_start._partition_banner_rows(rows)
        assert anchors == []
        assert [m["id"] for m in hot] == [3]

    def test_protected_anchor_tag_becomes_anchor(self):
        rows = [
            {
                "id": 1,
                "content": "anchored decision",
                "tags": ["_anchor"],
                "is_protected": True,
                "heat": 1.0,
            },
            {
                "id": 2,
                "content": "protected but not anchored",
                "tags": ["decision"],
                "is_protected": True,
                "heat": 0.9,
            },
            {
                "id": 3,
                "content": "scoped anchor",
                "tags": ["_anchor:project"],
                "is_protected": True,
                "heat": 1.0,
            },
        ]
        anchors, hot = session_start._partition_banner_rows(rows)
        assert [m["id"] for m in anchors] == [1, 3]
        assert [m["id"] for m in hot] == [2]

    def test_limits_applied(self):
        rows = [
            {"id": i, "content": f"m{i}", "tags": [], "heat": 0.9}
            for i in range(session_start._HOT_LIMIT + 10)
        ]
        _, hot = session_start._partition_banner_rows(rows)
        assert len(hot) == session_start._HOT_LIMIT


# ── session_start: full banner over a seeded store ───────────────────────


def test_sqlite_context_prints_banner_and_receipt(store, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    store.insert_memory(
        {
            "content": "sqlite-first install decision",
            "heat": 1.0,
            "is_protected": True,
            "tags": ["_anchor"],
        }
    )
    store.insert_memory({"content": "hot working memory", "heat": 0.9})
    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.get_shared_store", lambda: store
    )
    monkeypatch.setattr(session_start, "_print_external_sources", lambda: None)

    session_start._sqlite_context({"transcript_path": "/tmp/session-abc.jsonl"})

    out = capsys.readouterr().out
    assert "Cortex Memory Context" in out
    assert "sqlite-first install decision" in out
    assert "hot working memory" in out
    assert "⟦rcpt:" in out  # injection receipt marker stamped in header
    # The receipt row itself is resolvable (blame path parity).
    rows = store.fetch_injection_receipts([1])
    assert rows and rows[0]["channel"] == "session_start"


def test_sqlite_context_empty_store_prints_cold_start(store, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setattr(
        "mcp_server.infrastructure.memory_store.get_shared_store", lambda: store
    )
    monkeypatch.setattr(session_start, "_count_session_files", lambda: 0)

    session_start._sqlite_context({})

    out = capsys.readouterr().out
    # Cold-start message, and NEVER the PostgreSQL install instructions.
    assert "brew install postgresql" not in out
    assert "PostgreSQL" not in out


# ── auto_recall: FTS recall over a seeded store ──────────────────────────


class TestRecallMemoriesSqlite:
    def test_fts_match_with_heat_floor(self, store):
        store.insert_memory(
            {"content": "the resolver fix used topological sort", "heat": 0.8}
        )
        store.insert_memory({"content": "cold resolver note", "heat": 0.01})
        store.insert_memory({"content": "unrelated grocery list", "heat": 0.9})

        results = auto_recall._recall_memories_sqlite(store, "resolver fix")

        contents = [m["content"] for m in results]
        assert any("topological sort" in c for c in contents)
        assert all("grocery" not in c for c in contents)
        assert all(m["heat"] >= auto_recall._MIN_HEAT for m in results)

    def test_protected_first_and_benchmarks_excluded(self, store):
        store.insert_memory(
            {"content": "resolver benchmark row", "heat": 0.9, "is_benchmark": True}
        )
        store.insert_memory({"content": "resolver ordinary note", "heat": 0.9})
        store.insert_memory(
            {
                "content": "resolver protected decision",
                "heat": 0.5,
                "is_protected": True,
            }
        )

        results = auto_recall._recall_memories_sqlite(store, "resolver")

        assert results, "expected FTS hits"
        assert results[0]["protected"] is True
        assert all("benchmark row" not in m["content"] for m in results)

    def test_hostile_fts_input_degrades_to_empty(self, store):
        store.insert_memory({"content": "resolver note", "heat": 0.9})
        # FTS5 syntax characters must not raise (search_fts catches them).
        assert auto_recall._recall_memories_sqlite(store, 'a AND (b OR "') == []


def test_process_event_sqlite_injects_and_exits_zero(store, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    store.insert_memory(
        {"content": "the deploy script is resumable by design", "heat": 0.9}
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
    out = capsys.readouterr().out
    assert "Cortex context:" in out
    assert "resumable" in out
    assert "⟦rcpt:" in out
