"""Tests for the agent_briefing SubagentStart hook.

The hook is registered in ``.claude-plugin/plugin.json`` and invoked as
a process, which is why no module imports it — it is an entry point, not
a library (same shape as ``test_preemptive_context.py``). Every gate of
the event path, both briefing queries, and each way the briefing can
degrade are covered here.

Briefing is deliberately SILENT-skip when PostgreSQL is unreachable (the
plugin ships SQLite by default and README documents these
PostgreSQL-only enrichments as no-ops); the skip itself is still logged
to stderr — those log lines are the asserted signal.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.hooks import agent_briefing as hook


@pytest.fixture(autouse=True)
def _known_specialists(monkeypatch):
    """Pin the specialist set — the real one scans ~/.claude/agents/."""
    monkeypatch.setattr(hook, "_SPECIALIST_AGENTS", frozenset({"engineer", "dba"}))


# ── Frontmatter parsing ───────────────────────────────────────────────


def test_frontmatter_name_is_extracted(tmp_path: Path):
    md = tmp_path / "agent.md"
    md.write_text("---\nname: engineer\ndescription: x\n---\nbody")
    assert hook._parse_frontmatter_name(md) == "engineer"


def test_frontmatter_quoted_name_is_unquoted(tmp_path: Path):
    md = tmp_path / "agent.md"
    md.write_text('---\nname: "paper-writer"\n---\n')
    assert hook._parse_frontmatter_name(md) == "paper-writer"


def test_frontmatter_without_name_returns_none(tmp_path: Path):
    md = tmp_path / "agent.md"
    md.write_text("---\ndescription: no name here\n---\n")
    assert hook._parse_frontmatter_name(md) is None


def test_unreadable_agent_file_returns_none(tmp_path: Path):
    assert hook._parse_frontmatter_name(tmp_path / "absent.md") is None


# ── Specialist-set loading ────────────────────────────────────────────


def test_missing_agents_dir_falls_back_to_builtin_set(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert hook._load_specialist_agents() == hook._FALLBACK_AGENTS


def test_agents_dir_names_are_loaded_and_index_skipped(tmp_path, monkeypatch):
    agents = tmp_path / ".claude" / "agents"
    (agents / "genius").mkdir(parents=True)
    (agents / "engineer.md").write_text("---\nname: engineer\n---\n")
    (agents / "INDEX.md").write_text("---\nname: not-an-agent\n---\n")
    (agents / "genius" / "euler.md").write_text("---\nname: euler\n---\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    loaded = hook._load_specialist_agents()

    assert loaded == frozenset({"engineer", "euler"})
    assert "not-an-agent" not in loaded


def test_agents_dir_with_no_parsable_names_falls_back(tmp_path, monkeypatch):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "broken.md").write_text("no frontmatter at all")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert hook._load_specialist_agents() == hook._FALLBACK_AGENTS


# ── Keyword extraction ────────────────────────────────────────────────


def test_keywords_drop_stop_words_and_short_words():
    words = hook._extract_task_keywords("Please fix the reranker score for a bug")
    assert "reranker" in words and "score" in words
    assert "the" not in words and "for" not in words
    assert "please" not in words, "'please' is an explicit stop word"
    assert "a" not in words, "3-char-and-under words are dropped"


def test_keywords_are_stripped_deduped_and_capped_at_eight():
    prompt = "alpha, alpha! (beta) " + " ".join(f"word{i}xx" for i in range(20))
    words = hook._extract_task_keywords(prompt)
    assert words[0] == "alpha" and words[1] == "beta", "punctuation stripped"
    assert len(words) == len(set(words)), "duplicates removed"
    assert len(words) == 8, "capped at eight keywords"


def test_keywords_from_stop_words_only_prompt_is_empty():
    assert hook._extract_task_keywords("the and for that this with from") == []


# ── Connection ────────────────────────────────────────────────────────


def test_connect_without_psycopg_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)

    def _raise(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("no psycopg")
        return original(name, *args, **kwargs)

    original = __import__
    monkeypatch.setattr("builtins.__import__", _raise)
    assert hook._connect() is None


def test_connect_with_unreachable_database_returns_none(monkeypatch):
    module = MagicMock()
    module.connect.side_effect = RuntimeError("connection refused")
    monkeypatch.setitem(sys.modules, "psycopg", module)
    assert hook._connect() is None


# ── Briefing queries ──────────────────────────────────────────────────


def _row(mem_id: int, content: str, heat: float, agent: str) -> dict:
    return {"id": mem_id, "content": content, "heat": heat, "agent_context": agent}


def test_agent_scoped_memories_come_back_first_with_their_source():
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [_row(1, "prior work", 0.9, "engineer")],
        [_row(2, "team decision", 0.8, "dba")],
    ]

    results = hook._fetch_agent_context(conn, "engineer", ["reranker"])

    assert [r["id"] for r in results] == [1, 2]
    assert results[0]["source"] == "agent-prior"
    assert results[1]["source"] == "team:dba"


def test_full_first_pass_skips_the_team_query():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        _row(i, "prior", 0.9, "engineer") for i in range(hook._MAX_MEMORIES)
    ]

    results = hook._fetch_agent_context(conn, "engineer", ["kw"])

    assert len(results) == hook._MAX_MEMORIES
    assert conn.execute.call_count == 1, "no remaining slots — pass 2 skipped"


def test_no_keywords_skips_the_agent_scoped_query():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    hook._fetch_agent_context(conn, "engineer", [])

    assert conn.execute.call_count == 1, "only the team-decisions query ran"
    sql = conn.execute.call_args[0][0]
    assert "is_protected" in sql


def test_memory_content_is_truncated_to_300_chars():
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [_row(1, "x" * 1000, 0.9, "engineer")],
        [],
    ]

    results = hook._fetch_agent_context(conn, "engineer", ["kw"])

    assert len(results[0]["content"]) == 300


def test_failed_agent_scoped_query_is_logged_and_team_pass_still_runs(capsys):
    conn = MagicMock()
    first = MagicMock()
    first.fetchall.side_effect = RuntimeError("relation memories does not exist")
    second = MagicMock()
    second.fetchall.return_value = [_row(9, "decision", 0.7, "dba")]
    conn.execute.side_effect = [first, second]

    results = hook._fetch_agent_context(conn, "engineer", ["kw"])

    assert "agent-scoped query failed" in capsys.readouterr().err
    assert [r["id"] for r in results] == [9], "pass 2 degraded-continues"


def test_failed_team_query_is_logged_and_returns_partial_results(capsys):
    conn = MagicMock()
    first = MagicMock()
    first.fetchall.return_value = [_row(1, "prior", 0.9, "engineer")]
    second = MagicMock()
    second.fetchall.side_effect = RuntimeError("timeout")
    conn.execute.side_effect = [first, second]

    results = hook._fetch_agent_context(conn, "engineer", ["kw"])

    assert "team decisions query failed" in capsys.readouterr().err
    assert [r["id"] for r in results] == [1]


# ── Event processing gates ────────────────────────────────────────────


def _run(event: dict) -> None:
    with pytest.raises(SystemExit) as excinfo:
        hook.process_event(event)
    assert excinfo.value.code == 0, "the hook always exits 0 — never blocks"


def test_unknown_agent_is_skipped(capsys):
    with patch.object(hook, "_connect") as connect:
        _run({"agent_name": "Random-Agent", "prompt": "x" * 40})
    connect.assert_not_called()
    assert "not a specialist" in capsys.readouterr().err


def test_short_prompt_is_skipped(capsys):
    with patch.object(hook, "_connect") as connect:
        _run({"agent_name": "engineer", "prompt": "tiny"})
    connect.assert_not_called()
    assert "prompt too short" in capsys.readouterr().err


def test_prompt_without_keywords_is_skipped(capsys):
    with patch.object(hook, "_connect") as connect:
        _run({"agent_name": "engineer", "prompt": "the and for that this with from"})
    connect.assert_not_called()
    assert "no keywords" in capsys.readouterr().err


def test_unreachable_postgres_is_skipped_with_a_signal(capsys):
    with patch.object(hook, "_connect", return_value=None):
        _run({"agent_name": "engineer", "prompt": "improve reranker latency now"})
    assert "PostgreSQL unavailable" in capsys.readouterr().err


def test_no_relevant_memories_is_skipped_and_connection_closed(capsys):
    conn = MagicMock()
    with (
        patch.object(hook, "_connect", return_value=conn),
        patch.object(hook, "_fetch_agent_context", return_value=[]),
    ):
        _run({"agent_name": "engineer", "prompt": "improve reranker latency now"})
    assert "no relevant memories" in capsys.readouterr().err
    conn.close.assert_called_once()


# ── Successful briefing ───────────────────────────────────────────────

_MEMORIES = [
    {
        "id": 1,
        "content": "Reranker fix: cap at 32\nsecond line",
        "source": "agent-prior",
    },
    {"id": 2, "content": "Team: SQLite is the default", "source": "team:dba"},
]


def test_briefing_prints_header_marker_and_one_line_per_memory(capsys):
    conn = MagicMock()
    with (
        patch.object(hook, "_connect", return_value=conn),
        patch.object(hook, "_fetch_agent_context", return_value=_MEMORIES),
        patch.object(hook, "emit_hook_receipt", return_value=7) as receipt,
    ):
        _run({"agent_name": "Engineer", "prompt": "improve reranker latency now"})

    out, err = capsys.readouterr()
    assert "## Cortex Briefing (engineer)" in out
    assert hook.receipt_marker(7) in out, "receipt marker rides the header"
    assert "- [agent-prior] Reranker fix: cap at 32" in out
    assert "second line" not in out, "only the first line of a memory is injected"
    assert "- [team:dba] Team: SQLite is the default" in out
    assert "briefed engineer with 2 memories" in err
    conn.close.assert_called_once()
    receipt.assert_called_once()
    assert receipt.call_args.kwargs["channel"] == "agent_briefing"


def test_failed_receipt_degrades_to_marker_less_briefing(capsys):
    conn = MagicMock()
    with (
        patch.object(hook, "_connect", return_value=conn),
        patch.object(hook, "_fetch_agent_context", return_value=_MEMORIES),
        patch.object(hook, "emit_hook_receipt", return_value=None),
    ):
        _run({"agent_name": "engineer", "prompt": "improve reranker latency now"})

    out = capsys.readouterr().out
    assert "## Cortex Briefing (engineer)" in out
    assert "⟦rcpt:" not in out, "no receipt id — header carries no marker"


# ── stdin entry point ─────────────────────────────────────────────────


def test_main_ignores_an_interactive_terminal(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with patch.object(hook, "process_event") as processed:
        with pytest.raises(SystemExit):
            hook.main()
    processed.assert_not_called()


def test_main_ignores_empty_stdin(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: "  \n")
    with patch.object(hook, "process_event") as processed:
        with pytest.raises(SystemExit):
            hook.main()
    processed.assert_not_called()


def test_main_ignores_malformed_json(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: "{not json")
    with patch.object(hook, "process_event") as processed:
        with pytest.raises(SystemExit):
            hook.main()
    processed.assert_not_called()


def test_main_forwards_a_valid_event(monkeypatch):
    event = {"agent_name": "engineer", "prompt": "improve reranker latency now"}
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: json.dumps(event))
    with patch.object(hook, "process_event") as processed:
        hook.main()
    processed.assert_called_once_with(event)
