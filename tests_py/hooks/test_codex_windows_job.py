"""The Codex drain decides its Windows flags like mcp_server does (issue #684).

The Codex intake ships without mcp_server (ADR-1084), so its scripts repeat the
job probe and the decision. These tests hold the copy equal to the original:
the decision over every job state, the structure layout, the kernel32
bindings, and on win32 the real probe.

source: ADR-1102"""

from __future__ import annotations

import ctypes
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_server.shared import detached_spawn as d
from mcp_server.shared import win32_job as j

_SCRIPTS = Path(__file__).resolve().parents[2] / "plugins/hypermnesia-mcp-codex/scripts"
# source: ADR-1102 — every LimitFlags combination the decision distinguishes
_JOB_STATES = [
    None,
    0,
    j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    j.JOB_OBJECT_LIMIT_BREAKAWAY_OK,
    j.JOB_OBJECT_LIMIT_BREAKAWAY_OK | j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    j.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK,
    j.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK | j.JOB_OBJECT_LIMIT_BREAKAWAY_OK,
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"codex_{name}", _SCRIPTS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def codex_job():
    return _load("windows_job")


@pytest.fixture
def queue():
    return _load("session_queue")


@pytest.mark.parametrize("limits", _JOB_STATES)
def test_the_codex_decision_equals_the_shared_one(codex_job, limits):
    assert codex_job.creationflags(limits) == d.windows_creationflags(limits)


def _layout(structure) -> list:
    return [
        (name, _layout(kind) if issubclass(kind, ctypes.Structure) else kind)
        for name, kind in structure._fields_
    ]


def test_the_codex_structure_equals_the_shared_one(codex_job):
    assert _layout(codex_job.ExtendedLimits) == _layout(j.ExtendedLimits)
    assert ctypes.sizeof(codex_job.ExtendedLimits) == ctypes.sizeof(j.ExtendedLimits)


def _signatures(dll) -> dict:
    return {
        name: (getattr(dll, name).argtypes, getattr(dll, name).restype)
        for name in ("GetCurrentProcess", "IsProcessInJob", "QueryInformationJobObject")
    }


def _blank_dll() -> SimpleNamespace:
    return SimpleNamespace(
        GetCurrentProcess=SimpleNamespace(),
        IsProcessInJob=SimpleNamespace(),
        QueryInformationJobObject=SimpleNamespace(),
    )


def test_the_codex_bindings_equal_the_shared_ones(codex_job):
    ours = _signatures(codex_job.bind_kernel32(_blank_dll()))
    assert ours == _signatures(j.bind_kernel32(_blank_dll()))


class _Kernel32:
    """A process in a job whose limits read back as ``flags``; ``fail`` makes
    the named call return FALSE with last error 5."""

    def __init__(self, flags, fail=None) -> None:
        self.flags, self.fail = flags, fail

    def GetCurrentProcess(self):  # noqa: N802 — mirrors the kernel32 export name
        return -1

    def IsProcessInJob(self, process, job, result):  # noqa: N802 — mirrors the kernel32 export name
        if self.fail == "IsProcessInJob":
            return 0
        result._obj.value = int(self.flags is not None)
        return 1

    def QueryInformationJobObject(self, job, info_class, info, size, returned):  # noqa: N802 — mirrors the kernel32 export name
        if self.fail == "QueryInformationJobObject":
            return 0
        info._obj.BasicLimitInformation.LimitFlags = self.flags
        return 1


@pytest.mark.parametrize("limits", _JOB_STATES)
def test_the_codex_probe_reads_the_job_like_the_shared_one(
    codex_job, monkeypatch, limits
):
    monkeypatch.setattr(codex_job, "_last_error", lambda: 5)
    monkeypatch.setattr(j, "_last_error", lambda: 5)
    dll = _Kernel32(limits)
    assert codex_job.job_limit_flags_with(dll) == j.job_limit_flags_with(dll)


@pytest.mark.parametrize("call", ["IsProcessInJob", "QueryInformationJobObject"])
def test_an_unreadable_job_state_raises_in_the_codex_probe(
    codex_job, monkeypatch, call
):
    monkeypatch.setattr(codex_job, "_last_error", lambda: 5)
    with pytest.raises(OSError, match=rf"{call} failed \(Windows error 5\)"):
        codex_job.job_limit_flags_with(_Kernel32(0, fail=call))


def test_the_drain_detaches_with_the_measured_breakaway(queue, monkeypatch):
    monkeypatch.setattr(queue, "_WINDOWS", True)
    monkeypatch.setattr(
        queue._windows_job(), "job_limit_flags", lambda: j.JOB_OBJECT_LIMIT_BREAKAWAY_OK
    )
    assert queue.detach_options() == {
        "creationflags": d.windows_creationflags(j.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
    }


def test_an_unreadable_job_fails_the_drain_spawn(queue, monkeypatch):
    def unreadable():
        raise OSError("job state unreadable")

    monkeypatch.setattr(queue, "_WINDOWS", True)
    monkeypatch.setattr(queue._windows_job(), "job_limit_flags", unreadable)
    with pytest.raises(OSError, match="job state unreadable"):
        queue.detach_options()


def test_a_drain_bound_to_a_killing_job_is_reported(queue, monkeypatch, capsys):
    monkeypatch.setattr(queue, "_WINDOWS", True)
    monkeypatch.setattr(
        queue._windows_job(),
        "job_limit_flags",
        lambda: j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    )
    queue.detach_options()
    assert "ends when the job closes" in capsys.readouterr().err


def test_posix_drain_takes_a_new_session(queue, monkeypatch):
    monkeypatch.setattr(queue, "_WINDOWS", False)
    assert queue.detach_options() == {"start_new_session": True}


@pytest.mark.skipif(sys.platform != "win32", reason="needs the real kernel32")
def test_the_real_codex_probe_reads_what_the_shared_one_reads(codex_job):
    assert codex_job.job_limit_flags() == j.job_limit_flags()
