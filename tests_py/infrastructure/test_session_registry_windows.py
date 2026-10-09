"""Per-window session registry on Windows (issue #665), simulated.

Platform is switched with ``mcp_server.shared.platform.IS_WINDOWS`` and the
process table is a fake, so this runs on macOS, Linux and Windows alike. It
asserts the three causes of #665: no ``ps`` (the table is read through
``win32_process``), ``claude.exe`` names, and a server whose parent is
``cmd.exe`` (the reader walks to the ``claude.exe`` ancestor).

source: ADR-1096"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import mcp_server.infrastructure.session_registry as sr
from mcp_server.infrastructure import process_ancestry
from mcp_server.shared import platform as host_platform
from mcp_server.shared import win32_process
from tests_py.infrastructure.process_table_fakes import (
    CLAUDE_PID,
    HOOK_PID,
    SERVER_PID,
    FakeProcessTable,
)

# source: the cmd.exe pid in WINDOWS_WINDOW_TREE (process_table_fakes.py)
_CMD_EXE_PID = 50


@pytest.fixture
def table(monkeypatch, tmp_path):
    fake = FakeProcessTable()
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    monkeypatch.setattr(win32_process, "snapshot_rows", fake.snapshot)
    monkeypatch.setattr(win32_process, "creation_filetime", fake.creation)
    monkeypatch.setattr(win32_process, "pid_alive", lambda pid: pid in fake.created)

    def _no_ps(*_a, **_k):
        raise AssertionError("ps must not be spawned on the Windows path")

    monkeypatch.setattr(subprocess, "run", _no_ps)
    monkeypatch.setattr(sr, "registry_dir", lambda: tmp_path / "session-registry")
    sr._start_signature_cache.clear()
    process_ancestry._window_pid_cache.clear()
    yield fake
    sr._start_signature_cache.clear()
    process_ancestry._window_pid_cache.clear()


def _as_process(monkeypatch, own_pid: int, parent_pid: int) -> None:
    monkeypatch.setattr(os, "getpid", lambda: own_pid)
    monkeypatch.setattr(os, "getppid", lambda: parent_pid)


def test_hook_finds_claude_exe_without_ps(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    assert sr.find_claude_ancestor() == CLAUDE_PID


def test_hook_writes_the_entry_keyed_by_the_claude_exe_pid(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    assert sr.write_session("stem-1") is True
    path = sr.registry_path(CLAUDE_PID)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["claude_pid"] == CLAUDE_PID
    assert data["session_id"] == "stem-1"
    assert data["claude_start_time"] == str(table.created[CLAUDE_PID])


def test_server_behind_cmd_exe_reads_the_hooks_entry(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("stem-1")
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)  # getppid() is cmd.exe
    assert sr.current_window_session() == "stem-1"


def test_reader_does_not_key_on_getppid_on_windows(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("stem-1")
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)
    sr.current_window_session()
    assert not sr.registry_path(_CMD_EXE_PID).exists()


def test_two_windows_do_not_share_one_identity(table, monkeypatch):
    rows = [
        (10, 1, "Claude.exe", 100),
        (20, 10, "claude.exe", 200),
        (21, 10, "claude.exe", 210),
        (50, 20, "cmd.exe", 500),
        (51, 21, "cmd.exe", 510),
        (60, 50, "python.exe", 600),
        (61, 51, "python.exe", 610),
        (40, 20, "python.exe", 400),
        (41, 21, "python.exe", 410),
    ]
    two = FakeProcessTable(rows)
    monkeypatch.setattr(win32_process, "snapshot_rows", two.snapshot)
    monkeypatch.setattr(win32_process, "creation_filetime", two.creation)
    monkeypatch.setattr(win32_process, "pid_alive", lambda pid: pid in two.created)
    _as_process(monkeypatch, 40, 20)
    sr.write_session("window-a")
    _as_process(monkeypatch, 41, 21)
    sr.write_session("window-b")
    _as_process(monkeypatch, 60, 50)
    assert sr.current_window_session() == "window-a"
    process_ancestry._window_pid_cache.clear()
    _as_process(monkeypatch, 61, 51)
    assert sr.current_window_session() == "window-b"


def test_server_walk_runs_once_per_server_lifetime(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("stem-1")
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)
    table.snapshot_calls = 0
    for _ in range(3):
        assert sr.current_window_session() == "stem-1"
    assert table.snapshot_calls == 1


def test_session_id_is_still_read_fresh_every_call(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("before-clear")
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)
    assert sr.current_window_session() == "before-clear"
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("after-clear")
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)
    assert sr.current_window_session() == "after-clear"


def test_server_without_claude_ancestor_reads_none_and_does_not_cache(
    table, monkeypatch
):
    lonely = FakeProcessTable([(70, 1, "python.exe", 1)])
    monkeypatch.setattr(win32_process, "snapshot_rows", lonely.snapshot)
    _as_process(monkeypatch, 70, 1)
    assert sr.current_window_session() is None
    assert process_ancestry._window_pid_cache == {}


def test_recycled_claude_pid_is_rejected_by_start_signature(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("stem-1")
    table.created[CLAUDE_PID] = 999_999  # same pid, a different incarnation
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)
    assert sr.current_window_session() is None


def test_dead_claude_pid_reads_none(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("stem-1")
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)
    assert sr.current_window_session() == "stem-1"
    monkeypatch.setattr(win32_process, "pid_alive", lambda pid: False)
    assert sr.current_window_session() is None


def test_tombstone_clears_the_identity_and_keeps_lineage(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("stem-1")
    assert sr.tombstone(CLAUDE_PID) is True
    _as_process(monkeypatch, SERVER_PID, _CMD_EXE_PID)
    assert sr.current_window_session() is None
    assert sr.registry_path(CLAUDE_PID).exists()


def test_start_signature_unresolvable_writes_nothing(table, monkeypatch):
    _as_process(monkeypatch, HOOK_PID, 32)
    monkeypatch.setattr(win32_process, "creation_filetime", lambda pid: None)
    assert sr.write_session("stem-1", claude_pid=CLAUDE_PID) is False
    assert not sr.registry_path(CLAUDE_PID).exists()


def test_purge_and_active_scan_use_the_safe_probe(table, monkeypatch):
    def _no_kill(pid, sig):
        raise AssertionError(f"os.kill({pid}, {sig}) must not run on Windows")

    monkeypatch.setattr(os, "kill", _no_kill)
    _as_process(monkeypatch, HOOK_PID, 32)
    sr.write_session("stem-1")
    ghost = {
        "v": 1,
        "session_id": "ghost",
        "claude_pid": 4242,
        "claude_start_time": "x",
    }
    assert sr._atomic_write(sr.registry_path(4242), ghost)  # not in the table
    assert sr.has_active_session_window() is True
    assert sr.purge_dead_entries() == 1
    assert not sr.registry_path(4242).exists()
    assert sr.registry_path(CLAUDE_PID).exists()
