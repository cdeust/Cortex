"""``pid_alive``: the one liveness probe, on POSIX and simulated Windows.

``os.kill(pid, 0)`` is no existence check on Windows: CPython sends
``GenerateConsoleCtrlEvent(CTRL_C_EVENT == 0, pid)`` (Python docs ``os.kill``
3.10 to 3.13; ``Modules/posixmodule.c``), and any signal other than
CTRL_C_EVENT/CTRL_BREAK_EVENT is ``TerminateProcess``. These tests pin that no
caller of the probe reaches ``os.kill`` when the platform is Windows.

source: ADR-0597"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.infrastructure import groomer_coordinator_io, session_registry
from mcp_server.infrastructure.groomer_coordinator import GroomerCoordinator
from mcp_server.shared import platform as host_platform
from mcp_server.shared import process_liveness, win32_process

_LAUNCHER_FS = Path(__file__).resolve().parents[2] / "scripts" / "launcher_deps_fs.py"
_DEAD_PID_PROBE = "import os, sys; sys.stdout.write(str(os.getpid()))"


def _launcher_fs():
    spec = importlib.util.spec_from_file_location(
        "launcher_deps_fs_under_test", _LAUNCHER_FS
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tripwire(monkeypatch) -> list[tuple[int, int]]:
    calls: list[tuple[int, int]] = []

    def record(pid, sig):
        calls.append((pid, sig))
        raise AssertionError(
            f"os.kill({pid}, {sig}) reached on a simulated Windows host"
        )

    monkeypatch.setattr(os, "kill", record)
    return calls


def _callers():
    return [
        process_liveness.pid_alive,
        session_registry._pid_alive,
        groomer_coordinator_io.pid_alive,
        _launcher_fs().pid_alive,
    ]


def test_every_caller_shares_the_single_probe():
    assert {fn.__code__ for fn in _callers()} == {process_liveness.pid_alive.__code__}


@pytest.mark.parametrize("probe", _callers(), ids=lambda fn: fn.__module__)
def test_windows_never_reaches_os_kill(probe, monkeypatch):
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    seen = []
    monkeypatch.setattr(
        win32_process, "pid_alive", lambda pid: seen.append(pid) or True
    )
    calls = _tripwire(monkeypatch)
    assert probe(4242) is True
    assert calls == [] and seen == [4242]


def test_windows_answer_comes_from_the_win32_layer(monkeypatch):
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    monkeypatch.setattr(win32_process, "pid_alive", lambda pid: pid == 7)
    assert process_liveness.pid_alive(7) is True
    assert process_liveness.pid_alive(8) is False


def test_windows_probe_failure_propagates(monkeypatch):
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)

    def broken(pid):
        raise OSError(1, "undocumented failure")

    monkeypatch.setattr(win32_process, "pid_alive", broken)
    with pytest.raises(OSError):
        process_liveness.pid_alive(7)


def test_smallest_positive_pid_is_probed_on_windows(monkeypatch):
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    seen = []
    monkeypatch.setattr(
        win32_process, "pid_alive", lambda pid: seen.append(pid) or True
    )
    assert process_liveness.pid_alive(1) is True
    assert seen == [1]


@pytest.mark.parametrize("pid", [0, -1, -4242])
def test_non_positive_pid_is_dead_without_any_probe(pid, monkeypatch):
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    monkeypatch.setattr(win32_process, "pid_alive", lambda p: pytest.fail("probed"))
    calls = _tripwire(monkeypatch)
    assert process_liveness.pid_alive(pid) is False
    assert calls == []


def test_groomer_coordinator_counts_windows_sessions_without_os_kill(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    monkeypatch.setattr(win32_process, "pid_alive", lambda pid: pid == 111)
    calls = _tripwire(monkeypatch)
    coordinator = GroomerCoordinator("store-x", root=tmp_path)
    assert coordinator.register(111) and coordinator.register(222)
    assert coordinator.live_session_count() == 1
    assert not (coordinator.sessions_dir / "222.json").exists()
    coordinator.pid_path.write_text("111", encoding="utf-8")
    assert coordinator.is_groomer_running() is True
    assert calls == []


def test_launcher_sweeps_backup_owner_with_the_safe_probe(monkeypatch):
    fs = _launcher_fs()
    monkeypatch.setattr(host_platform, "IS_WINDOWS", True)
    monkeypatch.setattr(win32_process, "pid_alive", lambda pid: True)
    calls = _tripwire(monkeypatch)
    assert fs.pid_alive(31337) is True
    assert calls == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX os.kill(pid, 0) semantics")
class TestPosix:
    def test_own_pid_is_alive(self):
        assert process_liveness.pid_alive(os.getpid()) is True

    def test_exited_child_is_dead(self):
        child = subprocess.run(
            [sys.executable, "-c", _DEAD_PID_PROBE],
            capture_output=True,
            text=True,
            check=True,
        )
        assert process_liveness.pid_alive(int(child.stdout)) is False

    def test_permission_error_means_alive(self, monkeypatch):
        def deny(pid, sig):
            raise PermissionError

        monkeypatch.setattr(os, "kill", deny)
        assert process_liveness.pid_alive(5) is True

    def test_other_oserror_means_not_alive(self, monkeypatch):
        def fail(pid, sig):
            raise OSError("boom")

        monkeypatch.setattr(os, "kill", fail)
        assert process_liveness.pid_alive(5) is False

    def test_signal_zero_is_the_probe(self, monkeypatch):
        sent = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
        assert process_liveness.pid_alive(5) is True
        assert sent == [(5, 0)]
