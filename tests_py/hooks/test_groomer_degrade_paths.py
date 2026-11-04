"""#683: the two groomer-coordinator failure paths that still degraded silently.

1. ``is_groomer_running`` read every ``OSError`` on ``groomer.pid`` as "not
   running", so an unreadable file (EACCES, EIO) let the next SessionStart
   spawn a cycle while a live one may hold it.
2. ``_maybe_background_consolidate`` sent ANY exception to the legacy spawn,
   which bypasses the coordinator's lock and ``groomer.pid`` guard.

Each test fails on main before the fix: the unreadable file spawned a cycle,
and an unexpected coordinator exception took the legacy path.

source: ADR-1118 (amends ADR-0527 and ADR-1097 point 5)
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from mcp_server.infrastructure import groomer_coordinator, session_registry
from mcp_server.infrastructure.groomer_coordinator import (
    GroomerCoordinator,
    resolve_store_key,
)
from mcp_server.infrastructure.groomer_identity import GroomerPidUnreadableError


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def coord(cache) -> GroomerCoordinator:
    c = GroomerCoordinator(resolve_store_key())
    c.base_dir.mkdir(parents=True)
    return c


@pytest.fixture
def unreadable_pid_file(coord, monkeypatch):
    """``groomer.pid`` exists but reading it raises EACCES.

    The container runs as root, so chmod 000 would still be readable; the
    read itself is made to fail instead."""
    coord.pid_path.write_text(str(os.getpid()), encoding="utf-8")
    real_read = Path.read_text

    def read_text(self, *args, **kwargs):
        if self == coord.pid_path:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    return coord


@pytest.fixture
def start_hook(monkeypatch):
    """session_start_consolidate with the spawn and the legacy path recorded."""
    from mcp_server.hooks import session_start_consolidate as consolidate

    calls = {"spawn": 0, "legacy": 0, "log": []}

    def spawn(_options):
        calls["spawn"] += 1
        return os.getpid()

    def legacy():
        calls["legacy"] += 1

    monkeypatch.setattr(consolidate, "_spawn_consolidate_cycle", spawn)
    monkeypatch.setattr(consolidate, "_legacy_background_consolidate", legacy)
    monkeypatch.setattr(consolidate, "_log", calls["log"].append)
    monkeypatch.setattr(session_registry, "find_claude_ancestor", os.getppid)
    return consolidate, calls


def _errors(calls) -> list[str]:
    return [m for m in calls["log"] if m.startswith("ERROR")]


# ── path 1: groomer.pid ───────────────────────────────────────────────────


def test_missing_pid_file_reads_as_not_running(coord):
    assert coord.is_groomer_running() is False


@pytest.mark.parametrize("payload", [b"not-a-pid", b"\xff\xfe12"])
def test_unparseable_pid_file_reads_as_not_running(coord, payload):
    coord.pid_path.write_bytes(payload)
    assert coord.is_groomer_running() is False


def test_unreadable_pid_file_raises_a_named_error(unreadable_pid_file):
    with pytest.raises(GroomerPidUnreadableError, match="Permission denied"):
        unreadable_pid_file.is_groomer_running()


def test_unreadable_pid_file_spawns_no_cycle(unreadable_pid_file):
    spawned = []
    with pytest.raises(GroomerPidUnreadableError):
        unreadable_pid_file.ensure_cycle(
            period_hours=6.0, spawn_fn=lambda: spawned.append(1)
        )
    assert spawned == []
    assert not unreadable_pid_file.stamp_path.exists()


def test_session_start_with_unreadable_pid_file_fails_hard(
    start_hook, unreadable_pid_file
):
    consolidate, calls = start_hook
    consolidate._maybe_background_consolidate()

    assert calls["spawn"] == 0
    assert calls["legacy"] == 0, "no legacy bypass of the coordinator"
    assert not unreadable_pid_file.stamp_path.exists()
    assert list(unreadable_pid_file._iter_session_files()) == []
    errors = _errors(calls)
    assert len(errors) == 1 and "Permission denied" in errors[0]


# ── path 2: the hook boundary ─────────────────────────────────────────────


def test_unexpected_coordinator_exception_spawns_nothing(
    start_hook, coord, monkeypatch
):
    consolidate, calls = start_hook

    def broken(self, **_kwargs):
        raise KeyError("coordinator bug")

    monkeypatch.setattr(groomer_coordinator.GroomerCoordinator, "ensure_cycle", broken)
    consolidate._maybe_background_consolidate()

    assert calls["spawn"] == 0
    assert calls["legacy"] == 0, "a bug is not an I/O failure: no legacy spawn"
    errors = _errors(calls)
    assert len(errors) == 1 and "KeyError" in errors[0]


def test_coordinator_io_failure_keeps_the_documented_legacy_path(
    start_hook, coord, monkeypatch
):
    """ADR-1097 point 5, unchanged: I/O on the coordinator's own files."""
    consolidate, calls = start_hook

    def disk_full(self, _pid):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(groomer_coordinator.GroomerCoordinator, "register", disk_full)
    consolidate._maybe_background_consolidate()

    assert calls["legacy"] == 1
    assert calls["spawn"] == 0
    assert any("No space left on device" in m for m in calls["log"])
