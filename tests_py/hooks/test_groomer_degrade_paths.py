"""#683: groomer-coordinator failure paths that could start a cycle outside the lock.

1. ``is_groomer_running`` read every ``OSError`` on ``groomer.pid`` as "not
   running", so an unreadable file (EACCES, EIO) let the next SessionStart
   spawn a cycle while a live one may hold it.
2. ``_maybe_background_consolidate`` sent ANY exception to the legacy spawn,
   which bypasses the coordinator's lock and ``groomer.pid`` guard.
3. A spawn that raised ``OSError`` inside ``ensure_cycle`` left the lock and
   reached that legacy spawn.

The tests named ``unreadable``, ``unexpected`` and ``failed_spawn`` fail on
main; the others pin behaviour that stays unchanged.

source: ADR-1118 (amends ADR-0527 and ADR-1097 point 5)
"""

from __future__ import annotations

import errno
import json
import os
from datetime import datetime, timedelta, timezone
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
    monkeypatch.delenv("CORTEX_CACHE_DIR", raising=False)  # wins over XDG
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
    assert len(errors) == 1
    assert "GroomerPidUnreadableError" in errors[0]
    assert "Permission denied" in errors[0]
    assert "no consolidate cycle started" in errors[0]


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
    start_hook, tmp_path, monkeypatch
):
    """ADR-1097 point 5, unchanged: I/O on the coordinator's own files.

    A cache root that is a regular file makes ``ensure_cycle``'s ``mkdir``
    raise a real ``OSError`` (no monkeypatch; works as root)."""
    consolidate, calls = start_hook
    monkeypatch.delenv("CORTEX_CACHE_DIR", raising=False)  # wins over XDG
    not_a_dir = tmp_path / "cache-is-a-file"
    not_a_dir.write_text("", encoding="utf-8")
    monkeypatch.setenv("XDG_CACHE_HOME", str(not_a_dir))
    consolidate._maybe_background_consolidate()

    assert calls["legacy"] == 1
    assert calls["spawn"] == 0
    assert any("falling back to legacy" in m for m in calls["log"])


# ── a failed spawn inside the lock ────────────────────────────────────────


def test_spawn_returning_none_is_spawn_failed_and_keeps_the_period(coord):
    """ADR-1118 point 4 at the coordinator: stamped before the spawn, no
    ``groomer.pid``, not counted as a cycle, and no retry in the period."""
    since = datetime.now(timezone.utc) - timedelta(seconds=1)

    def stamped_then_fails():
        assert coord.stamp_path.exists(), "spawn_fn runs after the stamp"
        return

    outcome = coord.ensure_cycle(period_hours=6.0, spawn_fn=stamped_then_fails)

    assert outcome == groomer_coordinator.SPAWN_FAILED
    assert not coord.pid_path.exists()
    assert coord.count_cycles_since(since) == 0
    retried = []
    again = coord.ensure_cycle(period_hours=6.0, spawn_fn=lambda: retried.append(1))
    assert again == groomer_coordinator.SKIPPED_FRESH
    assert retried == []


@pytest.fixture
def failing_spawn_hook(coord, monkeypatch):
    """The real ``_spawn_consolidate_cycle`` with the legacy path recorded."""
    from mcp_server.hooks import session_start_consolidate as consolidate

    calls = {"legacy": 0, "log": []}

    def legacy():
        calls["legacy"] += 1

    monkeypatch.setattr(consolidate, "_legacy_background_consolidate", legacy)
    monkeypatch.setattr(consolidate, "_log", calls["log"].append)
    monkeypatch.setattr(session_registry, "find_claude_ancestor", os.getppid)
    return consolidate, calls


def _assert_stamped_spawn_failure(coord, calls, cause: str) -> None:
    assert calls["legacy"] == 0, "no second spawn outside the lock"
    assert coord.stamp_path.exists(), "the period stays stamped (ADR-1118 pt 4)"
    assert list(coord._iter_session_files()), "the window stays registered"
    last = json.loads(coord.log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert last["outcome"] == groomer_coordinator.SPAWN_FAILED
    errors = _errors(calls)
    assert len(errors) == 1 and cause in errors[0]


def test_failed_spawn_inside_the_lock_never_reaches_the_legacy_path(
    coord, failing_spawn_hook, monkeypatch
):
    """A Popen OSError (EAGAIN at the fork limit) used to leave ensure_cycle
    as an OSError and start a legacy cycle outside the lock (ADR-1118 pt 4)."""
    consolidate, calls = failing_spawn_hook

    def fork_limit(*_args, **_kwargs):
        raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")

    monkeypatch.setattr(consolidate, "spawn_logged", fork_limit)
    consolidate._maybe_background_consolidate()

    _assert_stamped_spawn_failure(coord, calls, "Resource temporarily unavailable")


def test_unresolvable_child_command_never_reaches_the_legacy_path(
    coord, failing_spawn_hook, monkeypatch
):
    """``launcher.exists()`` raises EACCES on an unsearchable parent."""
    consolidate, calls = failing_spawn_hook

    def unsearchable(_module):
        raise PermissionError(errno.EACCES, "Permission denied", "scripts")

    monkeypatch.setattr(consolidate, "child_command", unsearchable)
    consolidate._maybe_background_consolidate()

    _assert_stamped_spawn_failure(coord, calls, "Permission denied")
