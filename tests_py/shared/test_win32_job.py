"""``win32_job``: the job the current process runs in (issue #684).

Layout and bindings run everywhere; the logic of ``job_limit_flags_with`` runs
against a behavioural fake of kernel32; the real kernel32 runs on the Windows
CI leg only.

source: ADR-1102"""

from __future__ import annotations

import ctypes
import sys
import types

import pytest

from mcp_server.shared import win32_job as j

# source: winnt.h layout on a 64-bit build: basic limits 2*8 + 4 (+4 padding)
#   + 2*8 + 4 (+4) + 8 + 2*4 = 64 bytes; extended adds IO_COUNTERS (6*8) and
#   four SIZE_T (4*8) = 144 bytes
_BASIC_BYTES_64, _EXTENDED_BYTES_64 = 64, 144
# source: an arbitrary fake job-state value (no OS meaning)
_FAKE_FLAGS = 0x2800


class _FakeKernel32:
    def __init__(self, monkeypatch, *, in_job, flags=0) -> None:
        self.in_job, self.flags = in_job, flags
        self.is_in_job_ok = self.query_ok = True
        self.queries: list[tuple] = []
        self.error = 0
        monkeypatch.setattr(j, "_last_error", lambda: self.error)

    def GetCurrentProcess(self):  # noqa: N802 — mirrors the kernel32 export name
        return -1

    def IsProcessInJob(self, process, job, result):  # noqa: N802 — mirrors the kernel32 export name
        assert (process, job) == (-1, None)  # this process, any job
        if not self.is_in_job_ok:
            self.error = 6
            return 0
        result._obj.value = int(self.in_job)
        return 1

    def QueryInformationJobObject(self, job, info_class, info, size, returned):  # noqa: N802 — mirrors the kernel32 export name
        self.queries.append((job, info_class, size, returned))
        if not self.query_ok:
            self.error = 5
            return 0
        info._obj.BasicLimitInformation.LimitFlags = self.flags
        return 1


def test_no_job_reads_none_and_never_queries_limits(monkeypatch):
    dll = _FakeKernel32(monkeypatch, in_job=False)
    assert j.job_limit_flags_with(dll) is None
    assert dll.queries == []


def test_a_job_reads_its_limit_flags_from_the_extended_structure(monkeypatch):
    dll = _FakeKernel32(monkeypatch, in_job=True, flags=_FAKE_FLAGS)
    assert j.job_limit_flags_with(dll) == _FAKE_FLAGS
    # immediate job of the caller, extended class (9), whole structure
    assert dll.queries == [(None, 9, ctypes.sizeof(j.ExtendedLimits), None)]


def test_a_job_without_limits_is_still_a_job(monkeypatch):
    assert j.job_limit_flags_with(_FakeKernel32(monkeypatch, in_job=True)) == 0


@pytest.mark.parametrize("failing", ["is_in_job_ok", "query_ok"])
def test_an_unreadable_job_state_raises_instead_of_reading_no_job(monkeypatch, failing):
    dll = _FakeKernel32(monkeypatch, in_job=True)
    setattr(dll, failing, False)
    with pytest.raises(OSError, match=r"failed \(Windows error [56]\)") as raised:
        j.job_limit_flags_with(dll)
    assert raised.value.errno != dll.error, "a Win32 code is never an errno"


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="64-bit layout")
def test_structure_sizes_match_the_64_bit_winnt_layout():
    assert ctypes.sizeof(j.BasicLimits) == _BASIC_BYTES_64
    assert ctypes.sizeof(j.ExtendedLimits) == _EXTENDED_BYTES_64


def test_the_documented_limit_values():
    assert j.JOB_OBJECT_LIMIT_BREAKAWAY_OK == 0x00000800
    assert j.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK == 0x00001000
    assert j.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x00002000


def test_every_function_is_typed_so_handles_are_not_truncated():
    functions: dict[str, types.SimpleNamespace] = {}

    class Recording:
        def __getattr__(self, name):
            return functions.setdefault(name, types.SimpleNamespace())

    j.bind_kernel32(Recording())
    assert functions["GetCurrentProcess"].restype is ctypes.c_void_p
    assert functions["IsProcessInJob"].argtypes[:2] == [
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    assert functions["QueryInformationJobObject"].argtypes[0] is ctypes.c_void_p


@pytest.mark.skipif(sys.platform == "win32", reason="the refusal is off-Windows")
def test_the_real_probe_is_refused_off_windows():
    with pytest.raises(OSError, match="Windows-only"):
        j.job_limit_flags()


@pytest.mark.skipif(sys.platform != "win32", reason="needs the real kernel32")
def test_the_real_job_state_is_readable():
    flags = j.job_limit_flags()
    assert flags is None or flags >= 0
