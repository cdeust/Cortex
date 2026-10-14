"""The consolidate cycle decides its spawn options before it stamps a period.

An unreadable Windows job state is a spawn failure. On the coordinated path
(ADR-1097) it must leave no period stamp and no legacy retry of the probe, but
the window stays registered so another window's last-exit stop still counts
it; on the legacy path, no in-flight marker. Both paths spawn with
the options decided for this job (issue #684).

source: ADR-1102"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from mcp_server.infrastructure import session_registry
from mcp_server.infrastructure.groomer_coordinator import (
    GroomerCoordinator,
    resolve_store_key,
)
from mcp_server.shared import detached_spawn, win32_job
from tests_py._windows_spawn_fake import (
    as_windows_in_breakaway_job,
    assert_detached_on_windows,
)


def _unreadable_job():
    raise OSError("job state unreadable")


@pytest.fixture
def coordinated(monkeypatch, tmp_path):
    """session_start keyed by this live process, its spawn and legacy path
    recorded, the coordinator under tmp_path."""
    from mcp_server.hooks import session_start

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(session_registry, "find_claude_ancestor", os.getpid)
    calls = {"options": [], "legacy": 0, "log": []}

    def spawn(options):
        calls["options"].append(options)
        return os.getpid()

    def legacy():
        calls["legacy"] += 1

    monkeypatch.setattr(session_start, "_spawn_consolidate_cycle", spawn)
    monkeypatch.setattr(session_start, "_legacy_background_consolidate", legacy)
    monkeypatch.setattr(session_start, "_log", calls["log"].append)
    return session_start, calls, GroomerCoordinator(resolve_store_key())


@pytest.fixture
def legacy(monkeypatch, tmp_path):
    """The legacy path with its stamp under tmp_path and the spawn recorded."""
    from mcp_server.hooks import consolidate_background, session_start

    calls = {"options": [], "log": []}
    stamp = tmp_path / ".last_consolidate"
    monkeypatch.setattr(consolidate_background, "STAMP_PATH", stamp)
    monkeypatch.setattr(
        session_start, "_spawn_consolidate_cycle", calls["options"].append
    )
    monkeypatch.setattr(session_start, "_log", calls["log"].append)
    return session_start, calls, stamp


def test_unreadable_job_state_stamps_and_retries_nothing_but_registers(
    coordinated, monkeypatch
):
    session_start, calls, coord = coordinated
    monkeypatch.setattr(detached_spawn, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(win32_job, "job_limit_flags", _unreadable_job)

    session_start._maybe_background_consolidate()

    assert calls["options"] == []
    assert calls["legacy"] == 0, "a spawn failure never takes the legacy path"
    assert not coord.stamp_path.exists(), "no period stamped for no cycle"
    assert coord.live_session_count() == 1, "the open window is still counted"
    errors = [m for m in calls["log"] if "ERROR" in m]
    assert len(errors) == 1 and "job state unreadable" in errors[0]


def test_coordinated_cycle_spawns_with_the_options_decided_for_this_job(
    coordinated, monkeypatch
):
    session_start, calls, coord = coordinated
    as_windows_in_breakaway_job(monkeypatch)

    session_start._maybe_background_consolidate()

    assert coord.stamp_path.exists()
    assert len(calls["options"]) == 1
    assert_detached_on_windows(calls["options"][0])


def test_another_windows_exit_does_not_stop_while_a_probe_failed_window_is_open(
    coordinated, monkeypatch
):
    session_start, calls, coord = coordinated
    monkeypatch.setattr(detached_spawn, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(win32_job, "job_limit_flags", _unreadable_job)
    other_window = os.getppid()
    coord.register(other_window)
    session_start._maybe_background_consolidate()
    stopped = []

    assert coord.stop_if_last(other_window, stop_fn=lambda: stopped.append(1)) is False
    assert stopped == []


def test_legacy_path_with_unreadable_job_state_stamps_nothing(legacy, monkeypatch):
    session_start, calls, stamp = legacy
    monkeypatch.setattr(detached_spawn, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(win32_job, "job_limit_flags", _unreadable_job)

    session_start._legacy_background_consolidate()

    assert calls["options"] == []
    assert not stamp.exists(), "no in-flight marker for a cycle never started"
    assert any("job state unreadable" in m for m in calls["log"])


def test_legacy_path_spawns_with_the_options_decided_for_this_job(legacy, monkeypatch):
    session_start, calls, stamp = legacy
    as_windows_in_breakaway_job(monkeypatch)

    session_start._legacy_background_consolidate()

    assert stamp.exists()
    assert len(calls["options"]) == 1
    assert_detached_on_windows(calls["options"][0])
