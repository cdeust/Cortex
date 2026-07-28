"""Tests for the preemptive_context PostToolUse hook.

The hook is registered in ``.claude-plugin/plugin.json`` and invoked as a
process, which is why no module imports it — it is an entry point, not a
library. #196 covers it as one: every branch of the event path, the
cooldown, and each way priming can fail.

Priming is deliberately SILENT when the backend cannot be reached (the
plugin ships SQLite by default and README documents these PostgreSQL-only
enrichments as no-ops). Those tests assert the absence of a signal on
purpose — see ``test_missing_psycopg_is_silent``.

Paper backing for the mechanism itself lives in the module docstring
(Bar 2007; Collins & Loftus 1975; Smith & Vela 2001).
"""

from __future__ import annotations

import json
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.hooks import preemptive_context as hook


@pytest.fixture(autouse=True)
def _isolated_cooldown(tmp_path, monkeypatch):
    """Never touch the real shared cooldown file."""
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")


# ── Event gating ──────────────────────────────────────────────────────


@pytest.mark.parametrize("tool", ["Bash", "Grep", "Task", ""])
def test_non_file_tools_never_prime(tool):
    with patch.object(hook, "_prime_file_memories") as prime:
        hook.process_event({"tool_name": tool, "tool_input": {"file_path": "/a.py"}})
    prime.assert_not_called()


@pytest.mark.parametrize("tool", ["Edit", "Write", "Read"])
def test_file_tools_prime_the_touched_path(tool):
    with patch.object(hook, "_prime_file_memories", return_value=2) as prime:
        hook.process_event({"tool_name": tool, "tool_input": {"file_path": "/a.py"}})
    prime.assert_called_once_with("/a.py")


def test_missing_tool_input_does_not_prime():
    with patch.object(hook, "_prime_file_memories") as prime:
        hook.process_event({"tool_name": "Edit"})
    prime.assert_not_called()


def test_null_tool_input_does_not_prime():
    with patch.object(hook, "_prime_file_memories") as prime:
        hook.process_event({"tool_name": "Edit", "tool_input": None})
    prime.assert_not_called()


def test_empty_file_path_does_not_prime():
    with patch.object(hook, "_prime_file_memories") as prime:
        hook.process_event({"tool_name": "Read", "tool_input": {"file_path": ""}})
    prime.assert_not_called()


# ── Cooldown ──────────────────────────────────────────────────────────


def test_second_event_within_the_window_is_skipped():
    with patch.object(hook, "_prime_file_memories", return_value=3) as prime:
        hook.process_event({"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}})
        hook.process_event({"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}})
    assert prime.call_count == 1


def test_cooldown_is_per_file():
    with patch.object(hook, "_prime_file_memories", return_value=3) as prime:
        hook.process_event({"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}})
        hook.process_event({"tool_name": "Edit", "tool_input": {"file_path": "/b.py"}})
    assert prime.call_count == 2


def test_expired_cooldown_primes_again():
    stale = time.time() - hook._COOLDOWN_SECONDS - 1
    hook._COOLDOWN_FILE.write_text(json.dumps({"/a.py": stale}))

    with patch.object(hook, "_prime_file_memories", return_value=1) as prime:
        hook.process_event({"tool_name": "Read", "tool_input": {"file_path": "/a.py"}})

    prime.assert_called_once()


def test_priming_nothing_leaves_the_cooldown_unset():
    """A no-op prime must stay retryable — no cooldown, no log line."""
    with patch.object(hook, "_prime_file_memories", return_value=0):
        hook.process_event({"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}})

    assert not hook._COOLDOWN_FILE.exists()


def test_successful_prime_reports_the_file_it_primed(capsys):
    with patch.object(hook, "_prime_file_memories", return_value=4):
        hook.process_event(
            {"tool_name": "Edit", "tool_input": {"file_path": "/deep/path/store.py"}}
        )

    err = capsys.readouterr().err
    assert "primed 4 memories" in err
    assert "store.py" in err


def test_unreadable_cooldown_file_fails_open():
    hook._COOLDOWN_FILE.write_text("{ not json")

    assert hook._check_cooldown("/a.py") is False


def test_cooldown_file_is_pruned_to_fifty_entries():
    hook._COOLDOWN_FILE.write_text(
        json.dumps({f"/f{i}.py": float(i) for i in range(60)})
    )

    hook._update_cooldown("/new.py")

    data = json.loads(hook._COOLDOWN_FILE.read_text())
    assert len(data) == 50
    assert "/new.py" in data, "the newest entry must survive pruning"
    assert "/f0.py" not in data, "the oldest entries are the ones dropped"


def test_update_cooldown_recovers_from_a_corrupt_file():
    hook._COOLDOWN_FILE.write_text("garbage")

    hook._update_cooldown("/a.py")

    # Corrupt input is discarded rather than crashing the hook; the write
    # itself is best-effort, so the contract is only "no exception".
    assert hook._check_cooldown("/nonexistent.py") is False


# ── Priming ───────────────────────────────────────────────────────────


class _FakePgError(Exception):
    """Stands in for psycopg.Error — the class the hook's typed except pins."""


def _fake_psycopg(connect_result):
    module = MagicMock()
    module.Error = _FakePgError
    if isinstance(connect_result, Exception):
        module.connect.side_effect = connect_result
    else:
        module.connect.return_value = connect_result
    return module


def test_prime_boosts_matching_memories_and_returns_the_count(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value = MagicMock(rowcount=7)
    monkeypatch.setitem(sys.modules, "psycopg", _fake_psycopg(conn))

    assert hook._prime_file_memories("/repo/store.py") == 7

    sql, params = conn.execute.call_args[0]
    assert "heat_base" in sql and "heat_base_set_at" in sql
    assert params[0] == hook._HEAT_BOOST
    assert params[1] == "%/repo/store.py%"
    assert params[2] == "%store.py%", "the bare filename is the second cue"
    conn.close.assert_called_once()


def test_prime_excludes_benchmark_rows_and_already_hot_memories(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value = MagicMock(rowcount=0)
    monkeypatch.setitem(sys.modules, "psycopg", _fake_psycopg(conn))

    hook._prime_file_memories("/repo/a.py")

    sql = conn.execute.call_args[0][0]
    assert "NOT is_benchmark" in sql
    assert "heat_base < 1.0" in sql


def test_missing_psycopg_is_silent(monkeypatch, capsys):
    """SQLite installs have no psycopg — documented as a silent no-op."""
    monkeypatch.setitem(sys.modules, "psycopg", None)

    def _raise(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("no psycopg")
        return original(name, *args, **kwargs)

    original = __import__
    monkeypatch.setattr("builtins.__import__", _raise)

    assert hook._prime_file_memories("/a.py") == 0
    assert capsys.readouterr().err == "", "no noise on every file read"


def test_unreachable_database_is_silent(monkeypatch, capsys):
    monkeypatch.setitem(
        sys.modules, "psycopg", _fake_psycopg(_FakePgError("connection refused"))
    )

    assert hook._prime_file_memories("/a.py") == 0
    assert capsys.readouterr().err == ""


def test_failed_update_is_logged_with_its_cause(monkeypatch, capsys):
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("column heat_base does not exist")
    monkeypatch.setitem(sys.modules, "psycopg", _fake_psycopg(conn))

    assert hook._prime_file_memories("/a.py") == 0

    err = capsys.readouterr().err
    assert "prime failed" in err
    assert "column heat_base does not exist" in err
    conn.close.assert_called_once(), "the connection is closed even on failure"


# ── stdin entry point ─────────────────────────────────────────────────


def test_main_ignores_an_interactive_terminal(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with patch.object(hook, "process_event") as processed:
        hook.main()
    processed.assert_not_called()


def test_main_ignores_empty_stdin(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: "   \n")
    with patch.object(hook, "process_event") as processed:
        hook.main()
    processed.assert_not_called()


def test_main_ignores_malformed_json(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: "{not json")
    with patch.object(hook, "process_event") as processed:
        hook.main()
    processed.assert_not_called()


def test_main_forwards_a_valid_event(monkeypatch):
    event = {"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdin, "read", lambda: json.dumps(event))
    with patch.object(hook, "process_event") as processed:
        hook.main()
    processed.assert_called_once_with(event)
