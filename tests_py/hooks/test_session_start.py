"""Tests for the session_start SessionStart hook (#196).

The hook is registered in ``.claude-plugin/plugin.json`` and invoked as
a process — an entry point, not a library, which is why no module
imports it. These tests cover the banner-building contract: the event
gate, every fetch helper's shape and failure arm, the Markdown banner's
sections, the SQLite-backend path, and the cold-start message. All
database access goes through mock connections / fake stores; the
filesystem probes are pinned to ``tmp_path`` via ``Path.home``.

Failure arms in this hook are deliberately non-fatal (a broken query
must never break the SessionStart banner); each such arm's observable
contract is "degrades to empty + the banner still ships", and where the
code emits a stderr signal, that emission is asserted.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


from mcp_server.hooks import session_start as hook
from mcp_server.hooks import session_start_background as ss_background
from mcp_server.hooks import session_start_common as ss_common
from mcp_server.hooks import session_start_consolidate as ss_consolidate
from mcp_server.hooks import session_start_context as ss_context
from mcp_server.hooks import session_start_curation as ss_curation
from mcp_server.hooks import session_start_db as ss_db
from mcp_server.hooks import session_start_fetch as ss_fetch
from mcp_server.hooks import session_start_sources as ss_sources
from mcp_server.hooks import session_start_sqlite as ss_sqlite
from mcp_server.shared import detached_spawn
from tests_py.hooks._spawn_logged_fake import fake_spawn
from tests_py.hooks.stdin_support import utf8_stdin
from tests_py._windows_spawn_fake import (
    as_windows_in_breakaway_job,
    assert_detached_on_windows,
)

# ── Event reading ─────────────────────────────────────────────────────


def test_read_event_returns_empty_on_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert ss_common._read_event() == {}


def test_read_event_returns_empty_on_blank_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", utf8_stdin("  \n"))
    assert ss_common._read_event() == {}


def test_read_event_returns_empty_on_malformed_json(monkeypatch):
    monkeypatch.setattr(sys, "stdin", utf8_stdin("{nope"))
    assert ss_common._read_event() == {}


def test_read_event_parses_a_valid_event(monkeypatch):
    monkeypatch.setattr(sys, "stdin", utf8_stdin(json.dumps({"session_id": "s"})))
    assert ss_common._read_event() == {"session_id": "s"}


# ── Small helpers ─────────────────────────────────────────────────────


def test_short_collapses_newlines_and_truncates():
    assert ss_context._short("a\nb") == "a b"
    long = "x" * 200
    out = ss_context._short(long)
    assert out == "x" * 119 + "...", "keeps max_len-1 chars, appends ellipsis"


def test_parse_json_list_tolerates_every_input_shape():
    assert ss_db._parse_json_list(None) == []
    assert ss_db._parse_json_list(["a"]) == ["a"]
    assert ss_db._parse_json_list('["a", "b"]') == ["a", "b"]
    assert ss_db._parse_json_list("not json") == ["not json"]
    assert ss_db._parse_json_list("   ") == []


def test_checkpoint_from_row_maps_columns_and_none_passes_through():
    assert ss_db._checkpoint_from_row(None) is None
    cp = ss_db._checkpoint_from_row(
        {
            "current_task": "t",
            "next_steps": '["s1"]',
            "open_questions": [],
            "active_errors": None,
            "key_decisions": '["d"]',
            "directory_context": "/repo",
        }
    )
    assert cp == {
        "current_task": "t",
        "next_steps": ["s1"],
        "open_questions": [],
        "active_errors": [],
        "key_decisions": ["d"],
        "directory": "/repo",
    }


# ── PG fetch helpers (mock connections) ───────────────────────────────


def _conn_returning(rows):
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows
    return conn


def _failing_conn():
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("relation does not exist")
    return conn


def test_fetch_anchors_keeps_only_anchor_tagged_rows():
    rows = [
        {
            "id": 1,
            "content": "a",
            "tags": ["_anchor"],
            "domain": "d",
            "is_global": True,
        },
        {
            "id": 2,
            "content": "b",
            "tags": '["_anchor:x"]',
            "domain": "",
            "is_global": 0,
            "directory_context": "/repo",
        },
        {
            "id": 3,
            "content": "c",
            "tags": ["plain"],
            "domain": "",
            "is_global": False,
            "directory_context": "/repo",
        },
        {
            "id": 4,
            "content": "d",
            "tags": "{corrupt",
            "domain": "",
            "is_global": False,
            "directory_context": "/repo",
        },
    ]
    anchors = ss_fetch._fetch_anchors(_conn_returning(rows), "/repo")
    assert [a["id"] for a in anchors] == [1, 2]
    assert anchors[0]["is_global"] is True


def test_fetch_anchors_query_failure_degrades_to_empty():
    assert ss_fetch._fetch_anchors(_failing_conn(), "/repo") == []


# ── Project scoping (issue #604) ───────────────────────────────────────


def test_fetch_anchors_drops_other_project_keeps_global_and_ancestor():
    rows = [
        {
            "id": 1,
            "content": "other project's anchor",
            "tags": ["_anchor"],
            "domain": "",
            "is_global": False,
            "directory_context": "/other/project",
        },
        {
            "id": 2,
            "content": "global anchor",
            "tags": ["_anchor"],
            "domain": "",
            "is_global": True,
            "directory_context": "",
        },
        {
            "id": 3,
            "content": "ancestor-scoped anchor",
            "tags": ["_anchor"],
            "domain": "",
            "is_global": False,
            "directory_context": "/repo",
        },
        {
            "id": 4,
            "content": "empty directory_context is not a wildcard",
            "tags": ["_anchor"],
            "domain": "",
            "is_global": False,
            "directory_context": "",
        },
    ]
    anchors = ss_fetch._fetch_anchors(_conn_returning(rows), "/repo/subdir")
    assert [a["id"] for a in anchors] == [2, 3]


def test_fetch_team_decisions_excludes_ids_and_caps_at_three():
    rows = [
        {"id": i, "content": f"c{i}", "domain": "", "agent_context": "dba", "heat": 0.5}
        for i in range(1, 7)
    ]
    out = ss_fetch._fetch_team_decisions(_conn_returning(rows), exclude_ids={1})
    assert [d["id"] for d in out] == [2, 3, 4]
    assert out[0]["agent"] == "dba"


def test_fetch_team_decisions_query_failure_degrades_to_empty():
    assert ss_fetch._fetch_team_decisions(_failing_conn(), set()) == []


def test_fetch_hot_memories_excludes_ids_and_caps_at_limit():
    rows = [
        {
            "id": i,
            "content": f"c{i}",
            "domain": "d",
            "heat": 0.9,
            "tags": [],
            "is_global": False,
            "directory_context": "/repo",
        }
        for i in range(20)
    ]
    out = ss_fetch._fetch_hot_memories(_conn_returning(rows), {0, 1}, "/repo")
    assert len(out) == ss_sqlite._HOT_LIMIT
    assert out[0]["id"] == 2


def test_fetch_hot_memories_query_failure_degrades_to_empty():
    assert ss_fetch._fetch_hot_memories(_failing_conn(), set(), "/repo") == []


def test_fetch_hot_memories_drops_other_project_keeps_global_and_ancestor():
    rows = [
        {
            "id": 1,
            "content": "other project's hot memory",
            "domain": "",
            "heat": 0.9,
            "tags": [],
            "is_global": False,
            "directory_context": "/other/project",
        },
        {
            "id": 2,
            "content": "global hot memory",
            "domain": "",
            "heat": 0.9,
            "tags": [],
            "is_global": True,
            "directory_context": "",
        },
        {
            "id": 3,
            "content": "ancestor-scoped hot memory",
            "domain": "",
            "heat": 0.9,
            "tags": [],
            "is_global": False,
            "directory_context": "/repo",
        },
        {
            "id": 4,
            "content": "empty directory_context is not a wildcard",
            "domain": "",
            "heat": 0.9,
            "tags": [],
            "is_global": False,
            "directory_context": "",
        },
    ]
    out = ss_fetch._fetch_hot_memories(_conn_returning(rows), set(), "/repo/subdir")
    assert [m["id"] for m in out] == [2, 3]


def test_fetch_checkpoint_maps_the_row():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "current_task": "t",
        "next_steps": [],
        "open_questions": [],
        "active_errors": [],
        "key_decisions": [],
        "directory_context": "",
    }
    assert ss_db._fetch_checkpoint(conn)["current_task"] == "t"


def test_fetch_checkpoint_failure_degrades_to_none():
    assert ss_db._fetch_checkpoint(_failing_conn()) is None


def test_count_memories_reads_the_count_and_degrades_to_zero():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"c": 42}
    assert ss_db._count_memories(conn) == 42
    assert ss_db._count_memories(_failing_conn()) == 0


def test_grooming_staleness_never_run_reports_all_kinds_stale():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "wiki_last": None,
        "distill_last": None,
        "promo_last": None,
    }
    assert ss_curation._fetch_grooming_staleness(conn) == [
        "wiki",
        "distillation",
        "promotion",
    ]


def test_grooming_staleness_recent_runs_report_nothing():
    now = datetime.datetime.now(datetime.timezone.utc)
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "wiki_last": now,
        "distill_last": now,
        "promo_last": now,
    }
    assert ss_curation._fetch_grooming_staleness(conn) == []


def test_grooming_staleness_query_failure_degrades_to_empty():
    assert ss_curation._fetch_grooming_staleness(_failing_conn()) == []


def test_count_pending_curations_feeds_normalized_rows_to_the_curator(monkeypatch):
    from mcp_server.core import auto_curator

    seen: dict = {}

    def _fake_count(memories, wiki_root=None):
        seen["memories"] = memories
        seen["wiki_root"] = wiki_root
        return 4

    monkeypatch.setattr(auto_curator, "count_pending_clusters", _fake_count)
    rows = [
        {
            "id": 1,
            "content": None,
            "tags": None,
            "effective_heat": None,
            "created_at": None,
            "domain": None,
        }
    ]
    assert ss_curation._count_pending_curations(_conn_returning(rows)) == 4
    assert seen["memories"] == [
        {
            "id": 1,
            "content": "",
            "tags": [],
            "effective_heat": 0.0,
            "created_at": "",
            "domain": "",
        }
    ]


def test_count_pending_curations_failure_degrades_to_zero():
    assert ss_curation._count_pending_curations(_failing_conn()) == 0


def test_count_pending_curations_empty_sample_short_circuits(monkeypatch):
    from mcp_server.core import auto_curator

    def _never(*_a, **_k):
        raise AssertionError("curator must not run on an empty sample")

    monkeypatch.setattr(auto_curator, "count_pending_clusters", _never)
    assert ss_curation._count_pending_curations(_conn_returning([])) == 0


# ── Filesystem probes ─────────────────────────────────────────────────


def test_count_session_files_counts_jsonl_per_project(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ss_db._count_session_files() == 0
    proj = tmp_path / ".claude" / "projects" / "p1"
    proj.mkdir(parents=True)
    (proj / "a.jsonl").write_text("{}")
    (proj / "b.jsonl").write_text("{}")
    (proj / "ignored.txt").write_text("")
    assert ss_db._count_session_files() == 2


def test_detect_external_sources_empty_home_finds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert ss_sources._detect_external_sources() == []


def test_detect_external_sources_finds_claude_mem_cursor_and_chatgpt(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mem_dir = tmp_path / ".claude-mem"
    mem_dir.mkdir()
    db = sqlite3.connect(str(mem_dir / "claude-mem.db"))
    db.execute("CREATE TABLE observations (x)")
    db.execute("INSERT INTO observations VALUES (1)")
    db.commit()
    db.close()
    cursor = tmp_path / ".cursor" / "chats"
    cursor.mkdir(parents=True)
    (cursor / "conv.jsonl").write_text("{}")
    downloads = tmp_path / "Downloads" / "export"
    downloads.mkdir(parents=True)
    (downloads / "conversations.json").write_text("[]")

    names = {s["name"]: s["count"] for s in ss_sources._detect_external_sources()}

    assert names == {"claude-mem": 1, "Cursor": 1, "ChatGPT": 1}


def test_detect_external_sources_unreadable_claude_mem_reports_zero(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mem_dir = tmp_path / ".claude-mem"
    mem_dir.mkdir()
    (mem_dir / "claude-mem.db").write_text("not a database")

    sources = ss_sources._detect_external_sources()

    assert sources == [
        {"name": "claude-mem", "count": 0, "path": str(mem_dir / "claude-mem.db")}
    ]


# ── Banner building ───────────────────────────────────────────────────

_CP = {
    "current_task": "finish #196",
    "next_steps": ["a", "b", "c", "d"],
    "open_questions": ["q1", "q2", "q3"],
    "active_errors": ["e1", "e2", "e3"],
    "key_decisions": [],
    "directory": "/repo",
}


def test_checkpoint_section_caps_each_list():
    lines = ss_context._format_checkpoint_section(_CP)
    text = "\n".join(lines)
    assert "**Task:** finish #196" in text
    assert "`/repo`" in text
    assert text.count("- ") == 3 + 2 + 2, "3 steps, 2 errors, 2 questions"


def test_build_context_empty_inputs_yield_empty_banner():
    assert ss_context._build_context([], [], None) == ""


def test_checkpoint_section_truncates_long_fields_like_every_other_section():
    """Checkpoint fields must respect the same _short() cap already applied
    to anchors/team-decisions/hot memories — otherwise this is the one
    section of the per-turn-repeated banner that can grow unbounded."""
    long_task = "x" * 500
    cp = {
        "current_task": long_task,
        "next_steps": ["y" * 500],
        "open_questions": [],
        "active_errors": [],
        "key_decisions": [],
        "directory": "",
    }
    lines = ss_context._format_checkpoint_section(cp)
    text = "\n".join(lines)
    assert long_task not in text
    assert "y" * 500 not in text
    assert "..." in text


def test_build_context_renders_all_sections_and_receipt_marker():
    anchors = [{"id": 1, "content": "anchored fact", "domain": "", "is_global": False}]
    hot = [{"id": 2, "content": "hot fact", "domain": "cortex", "heat": 0.9}]
    team = [
        {"id": 3, "content": "team fact", "domain": "", "agent": "dba", "heat": 0.5}
    ]

    out = ss_context._build_context(
        anchors,
        hot,
        _CP,
        team_decisions=team,
        pending_curations=2,
        stale_grooming=["wiki"],
        receipt_id=9,
    )

    assert out.startswith("## Cortex Memory Context")
    assert ss_context.receipt_marker(9) in out
    assert "### Last Session State" in out
    assert "### Anchored Memories (critical)" in out
    assert "### Team Decisions" in out and "[dba] team fact" in out
    assert "[++++] [cortex] hot fact" in out, "heat bar + domain hint"
    assert "**2** topic clusters" in out
    assert "Grooming overdue (wiki)" in out
    assert "Use `recall` to retrieve full memories." in out


def test_short_line_carries_no_fetch_key():
    """An untruncated line needs no key — the whole memory is already there."""
    hot = [{"id": 42, "content": "short", "domain": "", "heat": 0.1}]
    out = ss_context._build_context([], hot, None)
    assert "short" in out
    assert ss_context.MEMORY_MARKER_PREFIX not in out
    assert "are truncated" not in out, "legend must not appear without a key"


def test_truncated_line_carries_its_memory_id_as_a_fetch_key():
    """The regression this closes: a cut banner line used to be a dead end.

    The reader could see content had been cut but had no handle to fetch
    the remainder — only a fresh search whose top hit is not guaranteed
    to be the same row. Every truncated line now ends in its own id.
    """
    long_content = "x" * 500
    anchors = [{"id": 7, "content": long_content, "domain": "", "is_global": False}]
    hot = [{"id": 8, "content": long_content, "domain": "cortex", "heat": 0.9}]
    team = [{"id": 9, "content": long_content, "domain": "", "agent": "dba"}]

    out = ss_context._build_context([], hot, None, team_decisions=team)
    out += ss_context._build_context(anchors, [], None)

    for memory_id in (7, 8, 9):
        assert ss_context.memory_marker(memory_id) in out, f"id {memory_id} lost"
    assert "..." in out, "still truncated — the key is added, not a bypass"
    assert long_content not in out, "the key must not smuggle in full content"


def test_fetch_key_legend_appears_only_when_a_key_was_emitted():
    truncated = [{"id": 3, "content": "y" * 500, "domain": "", "heat": 0.5}]
    assert "are truncated" in ss_context._build_context([], truncated, None)


def test_truncation_boundary_is_unchanged_by_the_fetch_key():
    """The key changes what a cut line CARRIES, never where it is cut."""
    content = "z" * 500
    body = ss_context._body({"id": 1, "content": content})
    assert body.startswith(ss_context._short(content))
    assert body == f"{ss_context._short(content)} {ss_context.memory_marker(1)}"


def test_build_context_without_receipt_has_no_marker():
    hot = [{"id": 2, "content": "hot", "domain": "", "heat": 0.1}]
    out = ss_context._build_context([], hot, None)
    assert "⟦rcpt:" not in out


def test_emit_banner_receipt_payload_mirrors_banner_order():
    conn = MagicMock()
    anchors = [{"id": 1}]
    team = [{"id": 2}]
    hot = [{"id": 3}]
    with patch.object(hook, "emit_hook_receipt", return_value=5) as emit:
        rid = hook._emit_banner_receipt(conn, {}, anchors, team, hot)
    assert rid == 5
    assert emit.call_args.args[1] == [
        {"memory_id": 1},
        {"memory_id": 2},
        {"memory_id": 3},
    ]
    assert emit.call_args.kwargs["channel"] == "session_start"


# ── Cold-start message ────────────────────────────────────────────────


def _unexpected_backfill() -> int:
    raise AssertionError("the backfill must not run for this setup result")


def test_cold_start_needs_install_names_the_configured_server_not_a_recipe():
    """ADR-1104: the real cause, never an install recipe."""
    msg = ss_context._build_cold_start_message(
        {"status": "needs_install", "message": "connection refused"},
        _unexpected_backfill,
    )
    assert "configured for Cortex is not reachable: connection refused" in msg
    assert "brew" not in msg


def test_cold_start_auth_failed_relays_the_message():
    msg = ss_context._build_cold_start_message(
        {"status": "auth_failed", "message": "bad pw"}, _unexpected_backfill
    )
    assert msg == "## Cortex — Database Authentication\n\nbad pw"


def test_cold_start_other_error_points_at_the_readme():
    msg = ss_context._build_cold_start_message(
        {"status": "broken", "message": "boom"}, _unexpected_backfill
    )
    assert "Setup issue: boom" in msg and "README" in msg


def test_cold_start_empty_db_with_history_reports_the_backfill_count():
    msg = ss_context._build_cold_start_message(
        {"status": "ready", "memories": 0, "session_files": 3}, lambda: 7
    )
    assert "auto-imported **7 memories**" in msg


def test_cold_start_empty_db_with_history_and_no_import_says_ready():
    msg = ss_context._build_cold_start_message(
        {"status": "ready", "memories": 0, "session_files": 3}, lambda: 0
    )
    assert "no memorable items" in msg


def test_cold_start_empty_db_without_history_says_ready():
    msg = ss_context._build_cold_start_message(
        {"status": "ready", "memories": 0}, _unexpected_backfill
    )
    assert "No previous sessions found" in msg


def test_cold_start_populated_db_yields_no_message():
    assert (
        ss_context._build_cold_start_message(
            {"status": "ready", "memories": 10}, _unexpected_backfill
        )
        == ""
    )


# ── SQLite banner path ────────────────────────────────────────────────


def _row(mem_id, **overrides):
    """is_global defaults True: these fixtures drive tag/limit logic, not
    the project-scoping predicate (covered separately below, issue #604).
    ``overrides`` may set tags, protected, heat and is_global."""
    return {
        "id": mem_id,
        "content": f"content {mem_id}",
        "domain": "",
        "heat": overrides.get("heat", 0.9),
        "tags": list(overrides.get("tags", ())),
        "is_protected": overrides.get("protected", False),
        "is_global": overrides.get("is_global", True),
        "directory_context": "",
    }


def test_partition_drops_noise_and_splits_anchors_from_hot():
    rows = [
        _row(1, tags=["auto-captured"]),
        _row(2, tags=["memory-replica"]),
        _row(3, tags=["_anchor"], protected=True),
        _row(4, tags=["_anchor"]),  # anchor tag WITHOUT protection -> hot
        _row(5),
    ]
    anchors, hot = ss_sqlite._partition_banner_rows(rows)
    assert [a["id"] for a in anchors] == [3]
    assert [h["id"] for h in hot] == [4, 5]


def test_partition_caps_both_pools():
    rows = [_row(i, tags=["_anchor"], protected=True) for i in range(10)]
    rows += [_row(100 + i) for i in range(20)]
    anchors, hot = ss_sqlite._partition_banner_rows(rows)
    assert len(anchors) == ss_sqlite._ANCHOR_LIMIT
    assert len(hot) == ss_sqlite._HOT_LIMIT


def test_partition_drops_other_project_keeps_global_and_ancestor():
    def _scoped_row(mem_id, directory_context, is_global=False):
        row = _row(mem_id, is_global=is_global)
        row["directory_context"] = directory_context
        return row

    rows = [
        _scoped_row(1, "/other/project"),
        _scoped_row(2, "", is_global=True),
        _scoped_row(3, "/repo"),
        _scoped_row(4, ""),
    ]
    _, hot = ss_sqlite._partition_banner_rows(rows, "/repo/subdir")
    assert [h["id"] for h in hot] == [2, 3]


def test_sqlite_banner_rows_fetch_failure_is_logged_and_degrades(capsys):
    store = MagicMock()
    store.get_hot_memories.side_effect = RuntimeError("no such table")
    store.get_active_checkpoint.side_effect = RuntimeError("no such table")

    anchors, hot, checkpoint = ss_sqlite._sqlite_banner_rows(store)

    assert (anchors, hot, checkpoint) == ([], [], None)
    assert "SQLite hot-memory fetch failed" in capsys.readouterr().err


def test_sqlite_context_prints_banner_and_emits_receipt(capsys, monkeypatch):
    from mcp_server.infrastructure import memory_store

    store = MagicMock()
    store.count_memories.return_value = {"total": 2}
    store.get_hot_memories.return_value = [_row(1), _row(2)]
    store.get_active_checkpoint.return_value = None
    monkeypatch.setattr(memory_store, "get_shared_store", lambda: store)

    emit = MagicMock(return_value=3)
    with patch.object(ss_sqlite, "_print_external_sources"):
        ss_sqlite._sqlite_context({}, _unexpected_backfill, emit)

    out, err = capsys.readouterr()
    assert "## Cortex Memory Context" in out
    assert ss_context.receipt_marker(3) in out
    assert "backend: sqlite" in err
    emit.assert_called_once()
    assert emit.call_args.args[0] is store
    assert [m["id"] for m in emit.call_args.args[1]] == [1, 2]


def test_sqlite_context_empty_store_prints_cold_start(capsys, monkeypatch, tmp_path):
    from mcp_server.infrastructure import memory_store

    store = MagicMock()
    store.count_memories.return_value = {"total": 0}
    monkeypatch.setattr(memory_store, "get_shared_store", lambda: store)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    ss_sqlite._sqlite_context({}, _unexpected_backfill, MagicMock())

    out = capsys.readouterr().out
    assert "## Cortex — First Run" in out


def test_sqlite_context_unavailable_store_logs_and_returns(capsys, monkeypatch):
    from mcp_server.infrastructure import memory_store

    def _boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(memory_store, "get_shared_store", _boom)

    ss_sqlite._sqlite_context({}, _unexpected_backfill, MagicMock())

    out, err = capsys.readouterr()
    assert out == "", "no banner when the store is unavailable"
    assert "SQLite store unavailable" in err


# ── Cached graph path ─────────────────────────────────────────────────


# Covered against a real SQLite store in test_session_start_cached_graph.py
# (issue #751).


# ── PG connection failure arm ─────────────────────────────────────────


def test_connect_pg_unreachable_server_logs_and_returns_none(capsys, monkeypatch):
    # Point at a closed port — never the developer's real server.
    monkeypatch.setattr(ss_db, "_DATABASE_URL", "postgresql://127.0.0.1:1/none")
    assert ss_db._connect_pg() is None
    assert "PostgreSQL connect failed" in capsys.readouterr().err


# ── Best-effort side channels ─────────────────────────────────────────


def test_refresh_session_registry_writes_and_purges(monkeypatch):
    from mcp_server.infrastructure import session_registry

    calls: list[str] = []
    monkeypatch.setattr(
        session_registry, "write_session", lambda sid, **_k: calls.append(f"w:{sid}")
    )
    monkeypatch.setattr(
        session_registry, "purge_dead_entries", lambda: calls.append("purge")
    )

    ss_background._refresh_session_registry({})

    assert calls == ["w:None", "purge"]


def test_refresh_session_registry_failure_is_logged_not_raised(capsys, monkeypatch):
    from mcp_server.infrastructure import session_registry

    def _boom(*_a, **_k):
        raise RuntimeError("registry io error")

    monkeypatch.setattr(session_registry, "write_session", _boom)

    ss_background._refresh_session_registry({})

    assert "session registry refresh skipped" in capsys.readouterr().err


def test_auto_wire_pipeline_logs_when_it_wires(capsys, monkeypatch):
    from mcp_server.infrastructure import pipeline_discovery

    monkeypatch.setattr(
        pipeline_discovery,
        "ensure_pipeline_connection",
        lambda project_root: {
            "action": "added_codebase",
            "binary": "ap",
            "path": "/cfg",
        },
    )

    ss_background._auto_wire_pipeline("/the/project")

    assert "pipeline auto-wired (ap)" in capsys.readouterr().err


def test_auto_wire_pipeline_noop_actions_stay_quiet(capsys, monkeypatch):
    from mcp_server.infrastructure import pipeline_discovery

    monkeypatch.setattr(
        pipeline_discovery,
        "ensure_pipeline_connection",
        lambda project_root: {"action": "already_present"},
    )

    ss_background._auto_wire_pipeline("/the/project")

    assert capsys.readouterr().err == ""


def test_auto_wire_pipeline_failure_is_logged_not_raised(capsys, monkeypatch):
    from mcp_server.infrastructure import pipeline_discovery

    def _boom(project_root):
        raise RuntimeError("discovery broke")

    monkeypatch.setattr(pipeline_discovery, "ensure_pipeline_connection", _boom)

    ss_background._auto_wire_pipeline("/the/project")

    assert "pipeline auto-wire skipped" in capsys.readouterr().err


def test_auto_backfill_reports_the_imported_count(capsys, monkeypatch):
    from mcp_server.handlers import backfill_memories

    async def _fake_handler(args):
        assert args["max_files"] == 100
        return {"backfilled": 5, "cascade_advanced": 2}

    monkeypatch.setattr(backfill_memories, "handler", _fake_handler)

    assert hook._auto_backfill() == 5
    assert "Auto-backfill: 5 imported, 2 cascaded" in capsys.readouterr().err


def test_auto_backfill_failure_is_logged_and_returns_zero(capsys, monkeypatch):
    from mcp_server.handlers import backfill_memories

    async def _boom(args):
        raise RuntimeError("backfill exploded")

    monkeypatch.setattr(backfill_memories, "handler", _boom)

    assert hook._auto_backfill() == 0
    assert "Auto-backfill failed (non-fatal)" in capsys.readouterr().err


# ── Background spawn: interpreter resolution (issue #315) ─────────────
# Both spawn helpers must resolve the interpreter via python_executable()
# (== sys.executable), never by resolving "python3"/"python" on PATH
# first — on Windows that hits the Microsoft Store stub and disables spawning.


class TestSpawnConsolidateCycleInterpreterResolution:
    def _write_launcher(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / "plugin"
        (plugin_root / "scripts").mkdir(parents=True)
        (plugin_root / "scripts" / "launcher.py").write_text("# stub\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return plugin_root

    def test_never_consults_shutil_which_and_builds_expected_command(
        self, tmp_path, monkeypatch, capsys
    ):
        """A PATH entry that would resolve to a stub interpreter must lose:
        the spawned command uses sys.executable regardless of what
        shutil.which("python3")/("python") would have returned.
        """
        plugin_root = self._write_launcher(tmp_path, monkeypatch)
        monkeypatch.setattr("shutil.which", lambda name: f"/fake/store-stub/{name}")
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return MagicMock(pid=4242)

        fake_spawn(monkeypatch, ss_consolidate, popen=_fake_popen)
        as_windows_in_breakaway_job(monkeypatch)

        assert ss_consolidate._spawn_consolidate_cycle(detached_spawn.options()) == 4242
        launcher = plugin_root / "scripts" / "launcher.py"
        assert captured["cmd"] == [
            sys.executable,
            str(launcher),
            "mcp_server.hooks.consolidate_background",
        ]
        assert "store-stub" not in captured["cmd"][0]
        assert_detached_on_windows(captured["kwargs"])
        log_path = tmp_path / ".claude" / "methodology" / "consolidate.log"
        # source: ADR-1110 — the log is written by the redaction relay
        assert captured["kwargs"]["log_path"] == log_path

        # A second cycle's spawn must also succeed (mkdir exist_ok=True).
        assert ss_consolidate._spawn_consolidate_cycle(detached_spawn.options()) == 4242
        err = capsys.readouterr().err
        assert f"background consolidate spawned → {log_path}" in err

    def test_falls_back_to_module_invocation_without_launcher(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "no-scripts-here"))
        monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock(pid=99)

        fake_spawn(monkeypatch, ss_consolidate, popen=_fake_popen)

        ss_consolidate._spawn_consolidate_cycle(detached_spawn.options())

        assert captured["cmd"] == [
            sys.executable,
            "-m",
            "mcp_server.hooks.consolidate_background",
        ]

    def test_falls_back_to_repo_root_without_plugin_root_env(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock(pid=1)

        fake_spawn(monkeypatch, ss_consolidate, popen=_fake_popen)

        ss_consolidate._spawn_consolidate_cycle(detached_spawn.options())
        expected_launcher = (
            Path(ss_consolidate.__file__).resolve().parents[2]
            / "scripts"
            / "launcher.py"
        )
        assert captured["cmd"][1] == str(expected_launcher)


class TestMaybeBackgroundReanalyzeInterpreterResolution:
    """Issue #315: same defect, same fix, as ``_spawn_reanalyze`` in
    ``post_commit_reindex.py`` — a PATH-resolved interpreter must never
    reach the spawned command.
    """

    def _mock_pipeline(self, monkeypatch, *, stale=True, cached="the-cached-path"):
        """Wire discover/lookup/staleness with MagicMocks (not plain
        lambdas) so a test can assert what argument each received — a
        lambda that ignores its argument cannot distinguish the real
        ``cached_path`` from a mutant that passes ``None`` through.
        """
        from mcp_server.infrastructure import pipeline_discovery, pipeline_graph_ttl

        discover_mock = MagicMock(return_value=["ap"])
        monkeypatch.setattr(
            pipeline_discovery, "discover_pipeline_command", discover_mock
        )
        self.discover_mock = discover_mock
        stale_mock = MagicMock(return_value=stale)
        monkeypatch.setattr(pipeline_graph_ttl, "graph_is_stale", stale_mock)
        lookup_mock = MagicMock(return_value=cached)
        self.lookup_mock = lookup_mock
        return stale_mock, lookup_mock

    def _write_launcher(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / "plugin"
        (plugin_root / "scripts").mkdir(parents=True)
        (plugin_root / "scripts" / "launcher.py").write_text("# stub\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
        monkeypatch.setenv("CLAUDE_PROJECT_ROOT", "/the/project")
        monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return plugin_root

    def test_never_consults_shutil_which_and_builds_expected_command(
        self, tmp_path, monkeypatch, capsys
    ):
        plugin_root = self._write_launcher(tmp_path, monkeypatch)
        stale_mock, lookup_mock = self._mock_pipeline(monkeypatch)
        monkeypatch.setattr("shutil.which", lambda name: f"/fake/store-stub/{name}")
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return MagicMock()

        fake_spawn(monkeypatch, ss_background, popen=_fake_popen)
        as_windows_in_breakaway_job(monkeypatch)

        ss_background._maybe_background_reanalyze("/the/project", self.lookup_mock)

        launcher = plugin_root / "scripts" / "launcher.py"
        assert captured["cmd"] == [
            sys.executable,
            str(launcher),
            "mcp_server.hooks.ingest_codebase_background",
            "/the/project",
        ]
        assert "store-stub" not in captured["cmd"][0]
        assert_detached_on_windows(captured["kwargs"])
        log_path = tmp_path / ".claude" / "methodology" / "pipeline_reanalyze.log"
        # source: ADR-1110 — the log is written by the redaction relay
        assert captured["kwargs"]["log_path"] == log_path
        # The cached-graph lookup result must actually flow into the
        # staleness check — not a look-alike constant.
        lookup_mock.assert_called_once_with("/the/project")
        self.discover_mock.assert_called_once_with("/the/project")
        stale_mock.assert_called_once_with("the-cached-path")
        assert "background pipeline reanalysis spawned" in capsys.readouterr().err

        # A second reanalyze must also succeed: the log directory already
        # exists on this call, exercising mkdir's exist_ok=True — a mutant
        # that drops/flips exist_ok raises FileExistsError, which the
        # broad except swallows into a "skipped" log instead of "spawned".
        # A zero TTL reopens the one-attempt-per-window slot (#751).
        monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "0")
        ss_background._maybe_background_reanalyze("/the/project", self.lookup_mock)
        err = capsys.readouterr().err
        assert "background pipeline reanalysis spawned" in err
        assert "skipped" not in err

    def test_falls_back_to_repo_root_without_plugin_root_env(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_ROOT", "/the/project")
        monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        self._mock_pipeline(monkeypatch)
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock()

        fake_spawn(monkeypatch, ss_background, popen=_fake_popen)

        ss_background._maybe_background_reanalyze("/the/project", self.lookup_mock)

        expected_launcher = (
            Path(ss_background.__file__).resolve().parents[2]
            / "scripts"
            / "launcher.py"
        )
        assert captured["cmd"][1] == str(expected_launcher)

    def test_ingests_the_given_root_never_the_cwd(self, tmp_path, monkeypatch):
        """Under scripts/launcher.py the cwd is the plugin root; ingesting
        it was the detached-worker leak the #679 guard reported."""
        self._write_launcher(tmp_path, monkeypatch)
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        monkeypatch.setattr(os, "getcwd", lambda: "/the/plugin-root")
        self._mock_pipeline(monkeypatch)
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock()

        fake_spawn(monkeypatch, ss_background, popen=_fake_popen)

        ss_background._maybe_background_reanalyze("/the/event-cwd", self.lookup_mock)

        assert captured["cmd"][-1] == "/the/event-cwd"
        self.discover_mock.assert_called_once_with("/the/event-cwd")

    def test_unresolved_project_root_spawns_nothing(self, monkeypatch, capsys):
        self._mock_pipeline(monkeypatch)

        with patch.object(ss_background, "spawn_logged") as popen:
            ss_background._maybe_background_reanalyze(None, self.lookup_mock)

        popen.assert_not_called()
        self.discover_mock.assert_not_called()
        assert "project root unresolved" in capsys.readouterr().err

    def test_skips_when_graph_fresh(self, tmp_path, monkeypatch):
        self._mock_pipeline(monkeypatch, stale=False)

        with patch.object(ss_background, "spawn_logged") as popen:
            ss_background._maybe_background_reanalyze("/the/project", self.lookup_mock)

        popen.assert_not_called()

    def test_skips_without_launcher(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "no-scripts-dir"))
        self._mock_pipeline(monkeypatch)

        with patch.object(ss_background, "spawn_logged") as popen:
            ss_background._maybe_background_reanalyze("/the/project", self.lookup_mock)

        popen.assert_not_called()

    def test_popen_failure_logs_and_is_swallowed(self, tmp_path, monkeypatch, capsys):
        self._write_launcher(tmp_path, monkeypatch)
        self._mock_pipeline(monkeypatch)

        def _boom(cmd, **kwargs):
            raise OSError("no such interpreter")

        fake_spawn(monkeypatch, ss_background, popen=_boom)

        ss_background._maybe_background_reanalyze(
            "/the/project", self.lookup_mock
        )  # must not raise

        err = capsys.readouterr().err
        assert "background pipeline reanalysis skipped" in err
        assert "no such interpreter" in err

    def test_success_logs_the_log_path(self, tmp_path, monkeypatch, capsys):
        self._write_launcher(tmp_path, monkeypatch)
        self._mock_pipeline(monkeypatch)
        fake_spawn(monkeypatch, ss_background)

        ss_background._maybe_background_reanalyze("/the/project", self.lookup_mock)

        err = capsys.readouterr().err
        assert "background pipeline reanalysis spawned" in err
        assert (
            str(tmp_path / ".claude" / "methodology" / "pipeline_reanalyze.log") in err
        )


# ── External source reporting ─────────────────────────────────────────


def test_print_external_sources_lists_each_source(capsys):
    sources = [
        {"name": "claude-mem", "count": 3, "path": "/db"},
        {"name": "Cursor", "count": 0, "path": "/c"},
    ]
    with patch.object(ss_sources, "_detect_external_sources", return_value=sources):
        ss_sources._print_external_sources()

    out = capsys.readouterr().out
    assert "### External Memory Sources Detected" in out
    assert "- **claude-mem** (3 items) — `/db`" in out
    assert "- **Cursor** — `/c`" in out, "zero-count sources omit the item count"
    assert "/cortex-import" in out


def test_print_external_sources_stays_silent_when_none_found(capsys):
    with patch.object(ss_sources, "_detect_external_sources", return_value=[]):
        ss_sources._print_external_sources()
    assert capsys.readouterr().out == ""


def test_print_external_sources_failure_is_logged_not_raised(capsys):
    with patch.object(
        ss_sources, "_detect_external_sources", side_effect=RuntimeError("scan died")
    ):
        ss_sources._print_external_sources()
    err = capsys.readouterr().err
    assert "External source detection failed (non-fatal)" in err


# ── main() dispatch ───────────────────────────────────────────────────


def _patched_main(**overrides):
    """Patch main()'s side-channel collaborators; return the patchers."""
    defaults = {
        "_read_event": MagicMock(return_value={}),
        "_refresh_session_registry": MagicMock(),
        "_auto_wire_pipeline": MagicMock(),
        "_maybe_background_reanalyze": MagicMock(),
        "_maybe_background_consolidate": MagicMock(),
        # ADR-1112: never touch the real ~/.cache/cortex from a test
        "harden_at_startup": MagicMock(),
    }
    defaults.update(overrides)
    return [patch.object(hook, name, m) for name, m in defaults.items()]


def _emitted(out: str) -> dict:
    """The hook's one JSON object (ADR-1104): status line and context."""
    return json.loads(out)


def _run_main(*extra_patches, **overrides):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _patched_main(**overrides):
            stack.enter_context(p)
        for p in extra_patches:
            stack.enter_context(p)
        hook.main()


def test_main_sqlite_backend_dispatches_to_the_sqlite_path(capsys):
    sqlite_ctx = MagicMock(return_value="Cortex ready: SQLite memory at ~/m.db")
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=True),
        patch.object(hook, "_sqlite_context", sqlite_ctx),
        patch.object(hook, "_connect_pg"),
    )
    sqlite_ctx.assert_called_once()
    assert _emitted(capsys.readouterr().out)["systemMessage"] == (
        "Cortex ready: SQLite memory at ~/m.db"
    )


def test_main_without_pg_and_failed_setup_prints_cold_start(capsys):
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=False),
        patch.object(hook, "_connect_pg", return_value=None),
        patch.object(hook, "_try_setup_db", return_value={"status": "needs_install"}),
    )
    emitted = _emitted(capsys.readouterr().out)
    assert "## Cortex — First Run" in emitted["hookSpecificOutput"]["additionalContext"]
    assert emitted["systemMessage"].startswith("Cortex not ready: ")
    assert "brew" not in json.dumps(emitted)


def test_main_setup_ready_but_still_unreachable_prints_the_ready_message(capsys):
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=False),
        patch.object(hook, "_connect_pg", return_value=None),
        patch.object(
            hook,
            "_try_setup_db",
            return_value={"status": "ready", "memories": 0, "session_files": 0},
        ),
    )
    out, err = capsys.readouterr()
    assert "Setup reported ready but still can't connect" in err
    assert "No previous sessions found" in out


def test_main_empty_database_prints_cold_start_and_closes_the_conn(capsys):
    conn = MagicMock()
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=False),
        patch.object(hook, "_connect_pg", return_value=conn),
        patch.object(hook, "_count_memories", return_value=0),
        patch.object(hook, "_count_session_files", return_value=0),
    )
    out = capsys.readouterr().out
    assert "No previous sessions found" in out
    conn.close.assert_called_once()


def test_main_normal_flow_prints_banner_receipt_and_closes_conn(capsys):
    conn = MagicMock()
    anchors = [{"id": 1, "content": "a", "domain": "", "is_global": False}]
    hot = [{"id": 2, "content": "h", "domain": "", "heat": 0.5}]
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=False),
        patch.object(hook, "_connect_pg", return_value=conn),
        patch.object(hook, "_count_memories", return_value=7),
        patch.object(hook, "_fetch_anchors", return_value=anchors),
        patch.object(hook, "_fetch_hot_memories", return_value=hot),
        patch.object(hook, "_fetch_team_decisions", return_value=[]),
        patch.object(hook, "_fetch_checkpoint", return_value=None),
        patch.object(hook, "_count_pending_curations", return_value=0),
        patch.object(hook, "_fetch_grooming_staleness", return_value=[]),
        patch.object(hook, "_emit_banner_receipt", return_value=11),
        patch.object(hook, "_print_external_sources"),
    )
    out, err = capsys.readouterr()
    emitted = _emitted(out)
    context = emitted["hookSpecificOutput"]["additionalContext"]
    assert "## Cortex Memory Context" in context
    assert ss_context.receipt_marker(11) in context
    assert emitted["systemMessage"].startswith(
        "Cortex ready: PostgreSQL memory store, 7 memories; "
    )
    assert "Injected 1 anchors + 1 hot memories (total: 7)" in err
    conn.close.assert_called_once()


def test_main_normal_flow_with_nothing_to_inject_logs_the_absence(capsys):
    conn = MagicMock()
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=False),
        patch.object(hook, "_connect_pg", return_value=conn),
        patch.object(hook, "_count_memories", return_value=7),
        patch.object(hook, "_fetch_anchors", return_value=[]),
        patch.object(hook, "_fetch_hot_memories", return_value=[]),
        patch.object(hook, "_fetch_team_decisions", return_value=[]),
        patch.object(hook, "_fetch_checkpoint", return_value=None),
        patch.object(hook, "_count_pending_curations", return_value=0),
        patch.object(hook, "_fetch_grooming_staleness", return_value=[]),
        patch.object(hook, "_emit_banner_receipt", return_value=None),
        patch.object(hook, "_print_external_sources"),
    )
    out, err = capsys.readouterr()
    assert _emitted(out)["hookSpecificOutput"]["additionalContext"] == ""
    assert "No memories above threshold" in err
