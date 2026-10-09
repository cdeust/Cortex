"""``win32_process``: the ctypes layer behind the Windows process table.

Two tiers here. (1) Structural tests: declared argtypes/restype, struct layout
and every documented constant, run on every platform against a recording fake
of kernel32. (3) ``win32``-only tests against the real kernel32, skipped
elsewhere (they run in CI job "Test (Windows, SQLite backend)"). Tier (2), the
logic of the ``*_with(dll, ...)`` functions, is ``test_win32_process_logic.py``.

source: ADR-1096"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import types

import pytest

from mcp_server.infrastructure import process_ancestry
from mcp_server.shared import win32_process as w

_ON_WINDOWS = sys.platform == "win32"
_WIN_ONLY = pytest.mark.skipif(
    not _ON_WINDOWS, reason="needs the real kernel32 (win32 only)"
)
_PTR_BYTES = ctypes.sizeof(ctypes.c_void_p)


class _RecordingDll:
    """Collects ``argtypes``/``restype`` assignments for any attribute."""

    def __init__(self) -> None:
        self.functions: dict[str, types.SimpleNamespace] = {}

    def __getattr__(self, name: str) -> types.SimpleNamespace:
        return self.functions.setdefault(
            name, types.SimpleNamespace(argtypes=None, restype=None)
        )


def test_documented_constants():
    assert w.TH32CS_SNAPPROCESS == 0x2
    assert w.PROCESS_QUERY_LIMITED_INFORMATION == 0x1000
    assert w.STILL_ACTIVE == 259
    assert w.MAX_PATH == 260
    assert (
        w.ERROR_ACCESS_DENIED,
        w.ERROR_NO_MORE_FILES,
        w.ERROR_INVALID_PARAMETER,
    ) == (5, 18, 87)


def test_access_mask_cannot_terminate_or_modify_a_process():
    # least privilege: query-limited only; PROCESS_TERMINATE is 0x0001
    assert w.PROCESS_QUERY_LIMITED_INFORMATION == 0x1000
    assert w.PROCESS_QUERY_LIMITED_INFORMATION & 0x0001 == 0


def test_every_function_has_declared_argtypes_and_restype():
    dll = w.bind_kernel32(_RecordingDll())
    c_void_p, u32, i32 = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    entry_ptr = ctypes.POINTER(w.ProcessEntry32W)
    time_ptr = ctypes.POINTER(w.FileTime)
    expected = {
        "OpenProcess": ([u32, i32, u32], c_void_p),
        "CloseHandle": ([c_void_p], i32),
        "GetExitCodeProcess": ([c_void_p, ctypes.POINTER(u32)], i32),
        "GetProcessTimes": ([c_void_p, time_ptr, time_ptr, time_ptr, time_ptr], i32),
        "CreateToolhelp32Snapshot": ([u32, u32], c_void_p),
        "Process32FirstW": ([c_void_p, entry_ptr], i32),
        "Process32NextW": ([c_void_p, entry_ptr], i32),
    }
    assert set(dll.functions) == set(expected)
    for name, (argtypes, restype) in expected.items():
        assert dll.functions[name].argtypes == argtypes, name
        assert dll.functions[name].restype is restype, name


def test_process_entry_field_order_and_types_match_processentry32w():
    expected = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),  # ULONG_PTR
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_int32),  # LONG
        ("dwFlags", ctypes.c_uint32),
    ]
    fields = w.ProcessEntry32W._fields_
    assert [(n, t) for n, t in fields[:-1]] == expected
    name, array = fields[-1]
    assert (
        name == "szExeFile" and array._type_ is ctypes.c_wchar and array._length_ == 260
    )


def test_process_entry_offsets_follow_natural_alignment():
    # dwSize,cntUsage,th32ProcessID are three DWORDs; ULONG_PTR then aligns
    entry = w.ProcessEntry32W
    assert (entry.dwSize.offset, entry.cntUsage.offset, entry.th32ProcessID.offset) == (
        0,
        4,
        8,
    )
    heap = entry.th32DefaultHeapID.offset
    assert heap == (16 if _PTR_BYTES == 8 else 12)
    assert entry.th32ParentProcessID.offset == heap + _PTR_BYTES + 8
    assert entry.szExeFile.offset == entry.dwFlags.offset + 4


def test_filetime_is_two_dwords():
    assert [(n, t) for n, t in w.FileTime._fields_] == [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]
    assert ctypes.sizeof(w.FileTime) == 8


@pytest.mark.skipif(_ON_WINDOWS, reason="the guard only fires off Windows")
def test_real_kernel32_is_refused_off_windows():
    with pytest.raises(OSError):
        w.pid_alive(1)
    with pytest.raises(OSError):
        w.snapshot_rows()
    with pytest.raises(OSError):
        w.creation_filetime(1)
    with pytest.raises(OSError) as excinfo:
        w._last_error()
    assert excinfo.value.args == ("win32_process is Windows-only",)


def test_last_error_reads_the_ctypes_thread_error_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 77, raising=False)
    assert w._last_error() == 77


# ── tier 3: the real kernel32 (win32 only) ───────────────────────────────


@_WIN_ONLY
def test_real_struct_size_matches_the_windows_abi():
    assert ctypes.sizeof(w.ProcessEntry32W) == (568 if _PTR_BYTES == 8 else 556)


@_WIN_ONLY
def test_real_own_pid_is_alive_and_a_bogus_pid_is_not():
    assert w.pid_alive(os.getpid()) is True
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert w.pid_alive(child.pid) is False


@_WIN_ONLY
def test_real_probe_does_not_terminate_a_live_process():
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert w.pid_alive(sleeper.pid) is True
        assert w.pid_alive(sleeper.pid) is True
        assert sleeper.poll() is None, "the liveness probe terminated its target"
    finally:
        sleeper.kill()
        sleeper.wait()


@_WIN_ONLY
def test_real_snapshot_contains_this_process_with_its_parent():
    rows = {row.pid: row for row in w.snapshot_rows()}
    me = rows[os.getpid()]
    assert me.ppid == os.getppid()
    assert me.exe_name.lower().startswith("python")


@_WIN_ONLY
def test_real_creation_time_is_stable_and_orders_parent_before_child():
    first = w.creation_filetime(os.getpid())
    assert first is not None and first > 0
    assert w.creation_filetime(os.getpid()) == first
    parent = w.creation_filetime(os.getppid())
    assert parent is not None and parent <= first


@_WIN_ONLY
def test_real_walk_finds_the_nearest_matching_ancestor():
    # claude.exe cannot be fabricated portably; the walk and the real table
    # are exercised by matching on the image name the snapshot reports for
    # the child's direct parent, whatever launcher started the test run.
    code = (
        "import os\n"
        "from mcp_server.infrastructure import process_ancestry as pa\n"
        "from mcp_server.shared import win32_process as w\n"
        "ppid = os.getppid()\n"
        "name = {r.pid: r.exe_name for r in w.snapshot_rows()}[ppid]\n"
        "pa._CLAUDE_EXE_NAME = name.lower()\n"
        "print(pa.claude_ancestor_pid(os.getpid(), 15), ppid)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    assert out[0] == out[1], "nearest same-named ancestor must be the direct parent"
    assert process_ancestry._CLAUDE_EXE_NAME == "claude.exe"


# source: a DWORD pid no Windows host assigns (pids are small multiples of 4)
_NO_SUCH_PID = 0xFFFFFFFC


@_WIN_ONLY
def test_real_nonexistent_pid_takes_the_invalid_parameter_path():
    assert w.pid_alive(_NO_SUCH_PID) is False
    assert w.creation_filetime(_NO_SUCH_PID) is None
