"""Logic of ``win32_process.*_with(dll, ...)`` against a behavioural fake of
kernel32 (issue #665). Runs on every platform; the real kernel32 is covered by
the ``win32``-only tests in ``test_win32_process.py``.

source: ADR-0597"""

from __future__ import annotations

import ctypes

import pytest

from mcp_server.shared import win32_process as w

# source: an arbitrary fake process handle value (no OS meaning)
_HANDLE = 0x1234
# source: an arbitrary fake snapshot handle value (no OS meaning)
_SNAPSHOT = 0x5678


# ── behavioural fake of kernel32 ────────────────────────────────────────


class _FakeKernel32:
    def __init__(self, monkeypatch) -> None:
        self.processes: dict[int, dict] = {}
        self.table: list[tuple[int, int, str]] = []
        self.snapshot_handle = _SNAPSHOT
        self.snapshot_end_error = w.ERROR_NO_MORE_FILES
        self.exit_code_ok = True
        self.times_ok = True
        self.open_error = w.ERROR_INVALID_PARAMETER
        self.error = 0
        self.closed: list[int] = []
        self.opened_with: list[tuple[int, int, int]] = []
        self.first_dwsize = None
        self._cursor = 0
        monkeypatch.setattr(w, "_last_error", lambda: self.error)

    def OpenProcess(self, access, inherit, pid):  # noqa: N802 — mirrors the kernel32 export name
        self.opened_with.append((access, inherit, pid))
        if pid not in self.processes:
            self.error = self.open_error
            return 0
        return _HANDLE + pid

    def CloseHandle(self, handle):  # noqa: N802 — mirrors the kernel32 export name
        self.closed.append(handle)
        return 1

    def GetExitCodeProcess(self, handle, out):  # noqa: N802 — mirrors the kernel32 export name
        if not self.exit_code_ok:
            self.error = 6
            return 0
        out.contents.value = self.processes[handle - _HANDLE]["exit"]
        return 1

    def GetProcessTimes(self, handle, created, exited, kernel, user):  # noqa: N802 — mirrors the kernel32 export name
        if not self.times_ok:
            self.error = 6
            return 0
        low_high = self.processes[handle - _HANDLE]["created"]
        created.contents.dwLowDateTime = low_high & 0xFFFFFFFF
        created.contents.dwHighDateTime = low_high >> 32
        return 1

    def CreateToolhelp32Snapshot(self, flags, pid):  # noqa: N802 — mirrors the kernel32 export name
        assert (flags, pid) == (w.TH32CS_SNAPPROCESS, 0)  # all processes, pid ignored
        if self.snapshot_handle in (None, 0, w._INVALID_HANDLE_VALUE):
            self.error = 5
        return self.snapshot_handle

    def _fill(self, entry_ptr):
        pid, ppid, name = self.table[self._cursor]
        entry = entry_ptr.contents
        entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile = (
            pid,
            ppid,
            name,
        )

    def Process32FirstW(self, snapshot, entry_ptr):  # noqa: N802 — mirrors the kernel32 export name
        assert snapshot == self.snapshot_handle
        self.first_dwsize = entry_ptr.contents.dwSize
        self._cursor = 0
        if not self.table:
            self.error = self.snapshot_end_error
            return 0
        self._fill(entry_ptr)
        return 1

    def Process32NextW(self, snapshot, entry_ptr):  # noqa: N802 — mirrors the kernel32 export name
        assert snapshot == self.snapshot_handle
        self._cursor += 1
        if self._cursor >= len(self.table):
            self.error = self.snapshot_end_error
            return 0
        self._fill(entry_ptr)
        return 1


@pytest.fixture
def k32(monkeypatch):
    return _FakeKernel32(monkeypatch)


def _add(k32, pid, *, exit_code=w.STILL_ACTIVE, created=0):
    k32.processes[pid] = {"exit": exit_code, "created": created}


def test_pid_alive_true_for_still_active(k32):
    _add(k32, 10)
    assert w.pid_alive_with(k32, 10) is True


def test_pid_alive_false_for_an_exited_process(k32):
    _add(k32, 10, exit_code=0)
    assert w.pid_alive_with(k32, 10) is False


def test_pid_alive_false_when_pid_does_not_exist(k32):
    assert w.pid_alive_with(k32, 99) is False


def test_pid_alive_true_when_access_is_denied(k32):
    k32.open_error = w.ERROR_ACCESS_DENIED
    assert w.pid_alive_with(k32, 99) is True


def test_pid_alive_raises_on_an_undocumented_open_error(k32):
    k32.open_error = 1450
    with pytest.raises(OSError):
        w.pid_alive_with(k32, 99)


def test_pid_alive_requests_query_limited_only_without_inheritance(k32):
    _add(k32, 10)
    w.pid_alive_with(k32, 10)
    assert k32.opened_with == [(0x1000, 0, 10)]


def test_pid_alive_closes_the_handle_on_success_and_on_failure(k32):
    _add(k32, 10)
    w.pid_alive_with(k32, 10)
    assert k32.closed == [_HANDLE + 10]
    k32.exit_code_ok = False
    with pytest.raises(OSError):
        w.pid_alive_with(k32, 10)
    assert k32.closed == [_HANDLE + 10, _HANDLE + 10]


def test_creation_filetime_joins_high_and_low_dwords(k32):
    _add(k32, 10, created=(0x01DC0000 << 32) | 0xDEADBEEF)
    assert w.creation_filetime_with(k32, 10) == (0x01DC0000 << 32) | 0xDEADBEEF
    assert k32.closed == [_HANDLE + 10]


@pytest.mark.parametrize("error", [5, 87])
def test_creation_filetime_none_when_gone_or_denied(k32, error):
    k32.open_error = error
    assert w.creation_filetime_with(k32, 10) is None


def test_creation_filetime_raises_on_undocumented_error_and_closes(k32):
    _add(k32, 10)
    k32.times_ok = False
    with pytest.raises(OSError):
        w.creation_filetime_with(k32, 10)
    assert k32.closed == [_HANDLE + 10]
    k32.open_error = 1450
    with pytest.raises(OSError):
        w.creation_filetime_with(k32, 11)


def test_snapshot_rows_lists_every_process_and_closes(k32):
    k32.table = [(4, 0, "System"), (20, 4, "claude.exe"), (30, 20, "cmd.exe")]
    assert w.snapshot_rows_with(k32) == [
        w.ProcessRow(4, 0, "System"),
        w.ProcessRow(20, 4, "claude.exe"),
        w.ProcessRow(30, 20, "cmd.exe"),
    ]
    assert k32.closed == [_SNAPSHOT]


def test_snapshot_rows_sets_dwsize_before_the_first_call(k32):
    k32.table = [(4, 0, "System")]
    w.snapshot_rows_with(k32)
    assert k32.first_dwsize == ctypes.sizeof(w.ProcessEntry32W)


def test_snapshot_rows_empty_snapshot_is_an_empty_list(k32):
    assert w.snapshot_rows_with(k32) == []


def test_snapshot_rows_abnormal_end_raises_and_closes(k32):
    k32.table = [(4, 0, "System"), (20, 4, "claude.exe")]
    k32.snapshot_end_error = 24  # ERROR_BAD_LENGTH: a truncated table
    with pytest.raises(OSError):
        w.snapshot_rows_with(k32)
    assert k32.closed == [_SNAPSHOT]


@pytest.mark.parametrize("handle", [None, 0, w._INVALID_HANDLE_VALUE])
def test_snapshot_rows_invalid_handle_raises(k32, handle):
    k32.snapshot_handle = handle
    with pytest.raises(OSError):
        w.snapshot_rows_with(k32)
    assert k32.closed == []


def _fields(error: OSError) -> tuple:
    return (error.errno, error.strerror, error.filename)


# ── failures carry the OS error code, the failing call and the pid ───────


def test_open_process_failure_reports_code_call_and_pid(k32):
    k32.open_error = 1450
    with pytest.raises(OSError) as excinfo:
        w.pid_alive_with(k32, 99)
    assert _fields(excinfo.value) == (1450, "OpenProcess failed", 99)
    with pytest.raises(OSError) as excinfo:
        w.creation_filetime_with(k32, 98)
    assert _fields(excinfo.value) == (1450, "OpenProcess failed", 98)


def test_get_exit_code_failure_reports_code_call_and_pid(k32):
    _add(k32, 10)
    k32.exit_code_ok = False
    with pytest.raises(OSError) as excinfo:
        w.pid_alive_with(k32, 10)
    assert _fields(excinfo.value) == (6, "GetExitCodeProcess failed", 10)


def test_get_process_times_failure_reports_code_call_and_pid(k32):
    _add(k32, 10)
    k32.times_ok = False
    with pytest.raises(OSError) as excinfo:
        w.creation_filetime_with(k32, 10)
    assert _fields(excinfo.value) == (6, "GetProcessTimes failed", 10)


def test_creation_filetime_requests_query_limited_only_without_inheritance(k32):
    _add(k32, 10)
    w.creation_filetime_with(k32, 10)
    assert k32.opened_with == [(0x1000, 0, 10)]


def test_snapshot_failure_reports_code_and_call(k32):
    k32.snapshot_handle = 0
    with pytest.raises(OSError) as excinfo:
        w.snapshot_rows_with(k32)
    assert _fields(excinfo.value) == (5, "CreateToolhelp32Snapshot failed", None)


def test_snapshot_abnormal_end_reports_code_and_call(k32):
    k32.table = [(4, 0, "System")]
    k32.snapshot_end_error = 24
    with pytest.raises(OSError) as excinfo:
        w.snapshot_rows_with(k32)
    assert _fields(excinfo.value) == (
        24,
        "Process32FirstW/NextW ended abnormally",
        None,
    )


# ── the public wrappers pass the pid through to a bound kernel32 ─────────


def test_public_wrappers_use_the_bound_kernel32_and_the_given_pid(k32, monkeypatch):
    monkeypatch.setattr(w, "_kernel32", lambda: k32)
    _add(k32, 10, created=77)
    k32.table = [(10, 4, "claude.exe")]
    assert w.pid_alive(10) is True
    assert w.creation_filetime(10) == 77
    assert w.snapshot_rows() == [w.ProcessRow(10, 4, "claude.exe")]
