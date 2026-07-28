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
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp_server.hooks import session_start as hook

# ── Event reading ─────────────────────────────────────────────────────


def test_read_event_returns_empty_on_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert hook._read_event() == {}


def test_read_event_returns_empty_on_blank_stdin(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: "  \n")
    assert hook._read_event() == {}


def test_read_event_returns_empty_on_malformed_json(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: "{nope")
    assert hook._read_event() == {}


def test_read_event_parses_a_valid_event(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: json.dumps({"session_id": "s"}))
    assert hook._read_event() == {"session_id": "s"}


# ── Small helpers ─────────────────────────────────────────────────────


def test_short_collapses_newlines_and_truncates():
    assert hook._short("a\nb") == "a b"
    long = "x" * 200
    out = hook._short(long)
    assert out == "x" * 119 + "...", "keeps max_len-1 chars, appends ellipsis"


def test_parse_json_list_tolerates_every_input_shape():
    assert hook._parse_json_list(None) == []
    assert hook._parse_json_list(["a"]) == ["a"]
    assert hook._parse_json_list('["a", "b"]') == ["a", "b"]
    assert hook._parse_json_list("not json") == ["not json"]
    assert hook._parse_json_list("   ") == []


def test_checkpoint_from_row_maps_columns_and_none_passes_through():
    assert hook._checkpoint_from_row(None) is None
    cp = hook._checkpoint_from_row(
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
        },
        {"id": 3, "content": "c", "tags": ["plain"], "domain": "", "is_global": False},
        {"id": 4, "content": "d", "tags": "{corrupt", "domain": "", "is_global": False},
    ]
    anchors = hook._fetch_anchors(_conn_returning(rows))
    assert [a["id"] for a in anchors] == [1, 2]
    assert anchors[0]["is_global"] is True


def test_fetch_anchors_query_failure_degrades_to_empty():
    assert hook._fetch_anchors(_failing_conn()) == []


def test_fetch_team_decisions_excludes_ids_and_caps_at_three():
    rows = [
        {"id": i, "content": f"c{i}", "domain": "", "agent_context": "dba", "heat": 0.5}
        for i in range(1, 7)
    ]
    out = hook._fetch_team_decisions(_conn_returning(rows), exclude_ids={1})
    assert [d["id"] for d in out] == [2, 3, 4]
    assert out[0]["agent"] == "dba"


def test_fetch_team_decisions_query_failure_degrades_to_empty():
    assert hook._fetch_team_decisions(_failing_conn(), set()) == []


def test_fetch_hot_memories_excludes_ids_and_caps_at_limit():
    rows = [
        {
            "id": i,
            "content": f"c{i}",
            "domain": "d",
            "heat": 0.9,
            "tags": [],
            "is_global": False,
        }
        for i in range(20)
    ]
    out = hook._fetch_hot_memories(_conn_returning(rows), exclude_ids={0, 1})
    assert len(out) == hook._HOT_LIMIT
    assert out[0]["id"] == 2


def test_fetch_hot_memories_query_failure_degrades_to_empty():
    assert hook._fetch_hot_memories(_failing_conn(), set()) == []


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
    assert hook._fetch_checkpoint(conn)["current_task"] == "t"


def test_fetch_checkpoint_failure_degrades_to_none():
    assert hook._fetch_checkpoint(_failing_conn()) is None


def test_count_memories_reads_the_count_and_degrades_to_zero():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {"c": 42}
    assert hook._count_memories(conn) == 42
    assert hook._count_memories(_failing_conn()) == 0


def test_grooming_staleness_never_run_reports_all_kinds_stale():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "wiki_last": None,
        "distill_last": None,
        "promo_last": None,
    }
    assert hook._fetch_grooming_staleness(conn) == ["wiki", "distillation", "promotion"]


def test_grooming_staleness_recent_runs_report_nothing():
    now = datetime.datetime.now(datetime.timezone.utc)
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "wiki_last": now,
        "distill_last": now,
        "promo_last": now,
    }
    assert hook._fetch_grooming_staleness(conn) == []


def test_grooming_staleness_query_failure_degrades_to_empty():
    assert hook._fetch_grooming_staleness(_failing_conn()) == []


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
    assert hook._count_pending_curations(_conn_returning(rows)) == 4
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
    assert hook._count_pending_curations(_failing_conn()) == 0


def test_count_pending_curations_empty_sample_short_circuits(monkeypatch):
    from mcp_server.core import auto_curator

    def _never(*_a, **_k):
        raise AssertionError("curator must not run on an empty sample")

    monkeypatch.setattr(auto_curator, "count_pending_clusters", _never)
    assert hook._count_pending_curations(_conn_returning([])) == 0


# ── Filesystem probes ─────────────────────────────────────────────────


def test_count_session_files_counts_jsonl_per_project(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert hook._count_session_files() == 0
    proj = tmp_path / ".claude" / "projects" / "p1"
    proj.mkdir(parents=True)
    (proj / "a.jsonl").write_text("{}")
    (proj / "b.jsonl").write_text("{}")
    (proj / "ignored.txt").write_text("")
    assert hook._count_session_files() == 2


def test_detect_external_sources_empty_home_finds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert hook._detect_external_sources() == []


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

    names = {s["name"]: s["count"] for s in hook._detect_external_sources()}

    assert names == {"claude-mem": 1, "Cursor": 1, "ChatGPT": 1}


def test_detect_external_sources_unreadable_claude_mem_reports_zero(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    mem_dir = tmp_path / ".claude-mem"
    mem_dir.mkdir()
    (mem_dir / "claude-mem.db").write_text("not a database")

    sources = hook._detect_external_sources()

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
    lines = hook._format_checkpoint_section(_CP)
    text = "\n".join(lines)
    assert "**Task:** finish #196" in text
    assert "`/repo`" in text
    assert text.count("- ") == 3 + 2 + 2, "3 steps, 2 errors, 2 questions"


def test_build_context_empty_inputs_yield_empty_banner():
    assert hook._build_context([], [], None) == ""


def test_build_context_renders_all_sections_and_receipt_marker():
    anchors = [{"id": 1, "content": "anchored fact", "domain": "", "is_global": False}]
    hot = [{"id": 2, "content": "hot fact", "domain": "cortex", "heat": 0.9}]
    team = [
        {"id": 3, "content": "team fact", "domain": "", "agent": "dba", "heat": 0.5}
    ]

    out = hook._build_context(
        anchors,
        hot,
        _CP,
        team_decisions=team,
        pending_curations=2,
        stale_grooming=["wiki"],
        receipt_id=9,
    )

    assert out.startswith("## Cortex Memory Context")
    assert hook.receipt_marker(9) in out
    assert "### Last Session State" in out
    assert "### Anchored Memories (critical)" in out
    assert "### Team Decisions" in out and "[dba] team fact" in out
    assert "[++++] [cortex] hot fact" in out, "heat bar + domain hint"
    assert "**2** topic clusters" in out
    assert "Grooming overdue (wiki)" in out
    assert "Use `recall` to retrieve full memories." in out


def test_build_context_without_receipt_has_no_marker():
    hot = [{"id": 2, "content": "hot", "domain": "", "heat": 0.1}]
    out = hook._build_context([], hot, None)
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


def test_cold_start_needs_install_shows_postgres_instructions():
    msg = hook._build_cold_start_message({"status": "needs_install"})
    assert "brew install postgresql" in msg


def test_cold_start_auth_failed_relays_the_message():
    msg = hook._build_cold_start_message({"status": "auth_failed", "message": "bad pw"})
    assert msg == "## Cortex — Database Authentication\n\nbad pw"


def test_cold_start_other_error_points_at_the_readme():
    msg = hook._build_cold_start_message({"status": "broken", "message": "boom"})
    assert "Setup issue: boom" in msg and "README" in msg


def test_cold_start_empty_db_with_history_reports_the_backfill_count():
    with patch.object(hook, "_auto_backfill", return_value=7):
        msg = hook._build_cold_start_message(
            {"status": "ready", "memories": 0, "session_files": 3}
        )
    assert "auto-imported **7 memories**" in msg


def test_cold_start_empty_db_with_history_and_no_import_says_ready():
    with patch.object(hook, "_auto_backfill", return_value=0):
        msg = hook._build_cold_start_message(
            {"status": "ready", "memories": 0, "session_files": 3}
        )
    assert "no memorable items" in msg


def test_cold_start_empty_db_without_history_says_ready():
    msg = hook._build_cold_start_message({"status": "ready", "memories": 0})
    assert "No previous sessions found" in msg


def test_cold_start_populated_db_yields_no_message():
    assert hook._build_cold_start_message({"status": "ready", "memories": 10}) == ""


# ── SQLite banner path ────────────────────────────────────────────────


def _row(mem_id, tags=(), protected=False, heat=0.9):
    return {
        "id": mem_id,
        "content": f"content {mem_id}",
        "domain": "",
        "heat": heat,
        "tags": list(tags),
        "is_protected": protected,
        "is_global": False,
    }


def test_partition_drops_noise_and_splits_anchors_from_hot():
    rows = [
        _row(1, tags=["auto-captured"]),
        _row(2, tags=["memory-replica"]),
        _row(3, tags=["_anchor"], protected=True),
        _row(4, tags=["_anchor"]),  # anchor tag WITHOUT protection -> hot
        _row(5),
    ]
    anchors, hot = hook._partition_banner_rows(rows)
    assert [a["id"] for a in anchors] == [3]
    assert [h["id"] for h in hot] == [4, 5]


def test_partition_caps_both_pools():
    rows = [_row(i, tags=["_anchor"], protected=True) for i in range(10)]
    rows += [_row(100 + i) for i in range(20)]
    anchors, hot = hook._partition_banner_rows(rows)
    assert len(anchors) == hook._ANCHOR_LIMIT
    assert len(hot) == hook._HOT_LIMIT


def test_sqlite_banner_rows_fetch_failure_is_logged_and_degrades(capsys):
    store = MagicMock()
    store.get_hot_memories.side_effect = RuntimeError("no such table")
    store.get_active_checkpoint.side_effect = RuntimeError("no such table")

    anchors, hot, checkpoint = hook._sqlite_banner_rows(store)

    assert (anchors, hot, checkpoint) == ([], [], None)
    assert "SQLite hot-memory fetch failed" in capsys.readouterr().err


def test_sqlite_context_prints_banner_and_emits_receipt(capsys, monkeypatch):
    from mcp_server.infrastructure import memory_store

    store = MagicMock()
    store.count_memories.return_value = {"total": 2}
    store.get_hot_memories.return_value = [_row(1), _row(2)]
    store.get_active_checkpoint.return_value = None
    monkeypatch.setattr(memory_store, "get_shared_store", lambda: store)

    with (
        patch.object(hook, "emit_injection_receipt", return_value=3) as emit,
        patch.object(hook, "_print_external_sources"),
    ):
        hook._sqlite_context({})

    out, err = capsys.readouterr()
    assert "## Cortex Memory Context" in out
    assert hook.receipt_marker(3) in out
    assert "backend: sqlite" in err
    emit.assert_called_once()


def test_sqlite_context_empty_store_prints_cold_start(capsys, monkeypatch, tmp_path):
    from mcp_server.infrastructure import memory_store

    store = MagicMock()
    store.count_memories.return_value = {"total": 0}
    monkeypatch.setattr(memory_store, "get_shared_store", lambda: store)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    hook._sqlite_context({})

    out = capsys.readouterr().out
    assert "## Cortex — First Run" in out


def test_sqlite_context_unavailable_store_logs_and_returns(capsys, monkeypatch):
    from mcp_server.infrastructure import memory_store

    def _boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(memory_store, "get_shared_store", _boom)

    hook._sqlite_context({})

    out, err = capsys.readouterr()
    assert out == "", "no banner when the store is unavailable"
    assert "SQLite store unavailable" in err


# ── Cached graph path ─────────────────────────────────────────────────


def test_lookup_cached_graph_path_reads_the_memo():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {"content": "graph_path=/tmp/graph.db  "}
    ]
    with patch.object(hook, "_connect_pg", return_value=conn):
        assert hook._lookup_cached_graph_path("/repo") == "/tmp/graph.db"
    conn.close.assert_called_once()


def test_lookup_cached_graph_path_without_pg_returns_none():
    with patch.object(hook, "_connect_pg", return_value=None):
        assert hook._lookup_cached_graph_path("/repo") is None


def test_lookup_cached_graph_path_ignores_non_memo_rows():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [{"content": "unrelated"}]
    with patch.object(hook, "_connect_pg", return_value=conn):
        assert hook._lookup_cached_graph_path("/repo") is None


# ── PG connection failure arm ─────────────────────────────────────────


def test_connect_pg_unreachable_server_logs_and_returns_none(capsys, monkeypatch):
    # Point at a closed port — never the developer's real server.
    monkeypatch.setattr(hook, "_DATABASE_URL", "postgresql://127.0.0.1:1/none")
    assert hook._connect_pg() is None
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

    hook._refresh_session_registry({})

    assert calls == ["w:None", "purge"]


def test_refresh_session_registry_failure_is_logged_not_raised(capsys, monkeypatch):
    from mcp_server.infrastructure import session_registry

    def _boom(*_a, **_k):
        raise RuntimeError("registry io error")

    monkeypatch.setattr(session_registry, "write_session", _boom)

    hook._refresh_session_registry({})

    assert "session registry refresh skipped" in capsys.readouterr().err


def test_auto_wire_pipeline_logs_when_it_wires(capsys, monkeypatch):
    from mcp_server.infrastructure import pipeline_discovery

    monkeypatch.setattr(
        pipeline_discovery,
        "ensure_pipeline_connection",
        lambda: {"action": "added_codebase", "binary": "ap", "path": "/cfg"},
    )

    hook._auto_wire_pipeline()

    assert "pipeline auto-wired (ap)" in capsys.readouterr().err


def test_auto_wire_pipeline_noop_actions_stay_quiet(capsys, monkeypatch):
    from mcp_server.infrastructure import pipeline_discovery

    monkeypatch.setattr(
        pipeline_discovery,
        "ensure_pipeline_connection",
        lambda: {"action": "already_present"},
    )

    hook._auto_wire_pipeline()

    assert capsys.readouterr().err == ""


def test_auto_wire_pipeline_failure_is_logged_not_raised(capsys, monkeypatch):
    from mcp_server.infrastructure import pipeline_discovery

    def _boom():
        raise RuntimeError("discovery broke")

    monkeypatch.setattr(pipeline_discovery, "ensure_pipeline_connection", _boom)

    hook._auto_wire_pipeline()

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


# ── External source reporting ─────────────────────────────────────────


def test_print_external_sources_lists_each_source(capsys):
    sources = [
        {"name": "claude-mem", "count": 3, "path": "/db"},
        {"name": "Cursor", "count": 0, "path": "/c"},
    ]
    with patch.object(hook, "_detect_external_sources", return_value=sources):
        hook._print_external_sources()

    out = capsys.readouterr().out
    assert "### External Memory Sources Detected" in out
    assert "- **claude-mem** (3 items) — `/db`" in out
    assert "- **Cursor** — `/c`" in out, "zero-count sources omit the item count"
    assert "/cortex-import" in out


def test_print_external_sources_stays_silent_when_none_found(capsys):
    with patch.object(hook, "_detect_external_sources", return_value=[]):
        hook._print_external_sources()
    assert capsys.readouterr().out == ""


def test_print_external_sources_failure_is_logged_not_raised(capsys):
    with patch.object(
        hook, "_detect_external_sources", side_effect=RuntimeError("scan died")
    ):
        hook._print_external_sources()
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
    }
    defaults.update(overrides)
    return [patch.object(hook, name, m) for name, m in defaults.items()]


def _run_main(*extra_patches, **overrides):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _patched_main(**overrides):
            stack.enter_context(p)
        for p in extra_patches:
            stack.enter_context(p)
        hook.main()


def test_main_sqlite_backend_dispatches_to_the_sqlite_path():
    sqlite_ctx = MagicMock()
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=True),
        patch.object(hook, "_sqlite_context", sqlite_ctx),
        patch.object(hook, "_connect_pg"),
    )
    sqlite_ctx.assert_called_once()


def test_main_without_pg_and_failed_setup_prints_cold_start(capsys):
    _run_main(
        patch.object(hook, "_backend_is_sqlite", return_value=False),
        patch.object(hook, "_connect_pg", return_value=None),
        patch.object(hook, "_try_setup_db", return_value={"status": "needs_install"}),
    )
    out = capsys.readouterr().out
    assert "## Cortex — First Run" in out
    assert "brew install postgresql" in out


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
    assert "## Cortex Memory Context" in out
    assert hook.receipt_marker(11) in out
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
    assert out == ""
    assert "No memories above threshold" in err
