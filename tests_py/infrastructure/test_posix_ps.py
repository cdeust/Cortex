"""Issue #682: ps status and decoding failures preserve their cause.

The subprocess boundary returns real bytes, including invalid UTF-8. Tests
exercise both registry callers and the hook's existing OSError failure path.
"""

from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from mcp_server.infrastructure import posix_ps, session_registry as sr


@pytest.fixture(autouse=True)
def posix_platform(monkeypatch):
    monkeypatch.setattr(sr.host_platform, "IS_WINDOWS", False)


@pytest.fixture
def probe_result(monkeypatch):
    result = subprocess.CompletedProcess(
        ["ps"], returncode=0, stdout=b"1 /usr/bin/claude\n", stderr=b""
    )
    run = Mock(return_value=result)
    monkeypatch.setattr(posix_ps.subprocess, "run", run)
    return result, run


@pytest.mark.parametrize("columns", ["lstart=", "ppid=,comm="])
def test_exit_one_preserves_command_and_stderr(probe_result, columns):
    result, _run = probe_result
    result.returncode = 1
    result.stdout = b"\xff"
    result.stderr = b"ps: unknown option \xff\n"

    with pytest.raises(posix_ps.PsProbeError) as caught:
        posix_ps.ps_output(columns, 123)

    error = caught.value
    assert isinstance(error, OSError)
    assert error.command == ["ps", "-o", columns, "-p", "123"]
    assert error.returncode == 1
    assert error.stderr == "ps: unknown option \\xff\n"
    assert "exit status 1" in str(error)
    assert "unknown option" in str(error)


def test_invalid_stdout_is_a_named_probe_error(probe_result):
    result, _run = probe_result
    result.stdout = b"1 /usr/bin/claude\xff\n"
    result.stderr = b"diagnostic\n"

    with pytest.raises(posix_ps.PsProbeError) as caught:
        sr._ppid_and_comm(123)

    assert isinstance(caught.value.__cause__, UnicodeDecodeError)
    assert caught.value.stderr == "diagnostic\n"
    assert caught.value.returncode == 0
    assert "utf-8" in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [OSError("ps unavailable"), subprocess.TimeoutExpired(["ps"], 1)],
)
def test_execution_failure_is_named_and_chained(monkeypatch, failure):
    monkeypatch.setattr(posix_ps.subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(posix_ps.PsProbeError) as caught:
        posix_ps.ps_output("ppid=,comm=", 123)
    assert caught.value.__cause__ is failure
    assert caught.value.command == ["ps", "-o", "ppid=,comm=", "-p", "123"]
    assert str(failure) in str(caught.value)


def test_happy_path_walk_and_byte_capture(probe_result, monkeypatch):
    _result, run = probe_result
    monkeypatch.setattr(sr.os, "getppid", lambda: 123)
    assert sr.find_claude_ancestor() == 123
    run.assert_called_once_with(
        ["ps", "-o", "ppid=,comm=", "-p", "123"],
        capture_output=True,
        timeout=posix_ps._PS_TIMEOUT_S,
        check=False,
    )


def test_start_signature_uses_checked_probe(probe_result, monkeypatch):
    result, _run = probe_result
    monkeypatch.setattr(sr.Path, "exists", lambda _path: False)
    result.stdout = b"Sat Oct 10 12:34:56 2026\n"
    assert sr._process_start_signature(123) == "Sat Oct 10 12:34:56 2026"
    result.returncode = 1
    result.stderr = b"ps failed"
    with pytest.raises(posix_ps.PsProbeError, match="ps failed"):
        sr._process_start_signature(123)


def test_empty_success_still_means_no_process(probe_result):
    result, _run = probe_result
    result.stdout = b""
    assert sr._ppid_and_comm(123) is None


@pytest.mark.parametrize(
    ("status", "stdout", "diagnostic"),
    [(1, b"", "exit status 1"), (0, b"1 claude\xff", "utf-8")],
)
def test_hook_reports_probe_cause_without_legacy_spawn(
    monkeypatch, tmp_path, status, stdout, diagnostic
):
    from mcp_server.hooks import session_start_consolidate as hook
    from mcp_server.infrastructure import groomer_coordinator

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(sr.os, "getppid", lambda: 123)
    monkeypatch.setattr(
        posix_ps.subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                ["ps"], status, stdout=stdout, stderr=b"probe diagnostic"
            )
        ),
    )
    coordinator = Mock()
    monkeypatch.setattr(
        groomer_coordinator, "GroomerCoordinator", lambda _key: coordinator
    )
    monkeypatch.setattr(groomer_coordinator, "resolve_store_key", lambda: "test-store")
    logged, spawn, legacy = [], Mock(), Mock()
    monkeypatch.setattr(hook, "_log", logged.append)
    monkeypatch.setattr(hook, "_spawn_consolidate_cycle", spawn)
    monkeypatch.setattr(hook, "_legacy_background_consolidate", legacy)

    hook._maybe_background_consolidate()

    spawn.assert_not_called()
    legacy.assert_not_called()
    coordinator.register.assert_not_called()
    coordinator.ensure_cycle.assert_not_called()
    assert len(logged) == 1
    assert "ERROR" in logged[0]
    assert diagnostic in logged[0]
    assert "probe diagnostic" in logged[0]
    assert "ppid=,comm=" in logged[0]
    assert "no claude ancestor" not in logged[0]
