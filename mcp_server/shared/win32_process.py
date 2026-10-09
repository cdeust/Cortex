"""Windows process primitives over ``ctypes`` (kernel32 only, no dependency).

Layer: shared (stdlib only). The one place that talks to the Windows process
table: a snapshot of ``(pid, ppid, exe_name)`` rows, a process creation time,
and a liveness probe. Everything above this module (the ancestor walk, the
platform dispatch of ``process_liveness``) is plain Python over these three
functions and is exercised on every platform with a fake; this module itself
is exercised for real only on ``win32``.

Why never ``os.kill`` on Windows (ADR-1096): CPython's ``os_kill_impl``
(``Modules/posixmodule.c``) sends ``CTRL_C_EVENT`` (0) and ``CTRL_BREAK_EVENT``
(1) to ``GenerateConsoleCtrlEvent(sig, pid)``. In 3.10, 3.11, 3.12.0 to 3.12.8
and 3.13.0 to 3.13.1 (tags read; 3.10 and 3.11 never fixed) a failed call does
not return: it falls through to ``OpenProcess(PROCESS_ALL_ACCESS)`` and
``TerminateProcess(handle, sig)``, so a probe of a live pid in another console
could kill it with exit code 0 (gh-58689, fixed in 3.12.9 and 3.13.2 by
gh-128932); after a successful kill the function raises ``SystemError``, which
``except OSError`` does not catch. A pid that is not a process group id on the
caller's console acts as group 0, a Ctrl+C to every process on that console
(gh-87128). Signal 0 is therefore no existence check and a live pid is a
hazard, not an input.

source: ADR-1096"""

from __future__ import annotations

import ctypes
import functools
import sys
from typing import Any, NamedTuple


class ProcessRow(NamedTuple):
    """One process as the OS reports it: ``exe_name`` is the bare file name."""

    pid: int
    ppid: int
    exe_name: str


# source: TH32CS_SNAPPROCESS = 0x00000002, learn.microsoft.com/windows/win32/
#   api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot
TH32CS_SNAPPROCESS = 0x00000002

# source: PROCESS_QUERY_LIMITED_INFORMATION = 0x1000, learn.microsoft.com/
#   windows/win32/procthread/process-security-and-access-rights
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# source: STILL_ACTIVE = 259, learn.microsoft.com/windows/win32/api/
#   processthreadsapi/nf-processthreadsapi-getexitcodeprocess
STILL_ACTIVE = 259

# source: learn.microsoft.com/windows/win32/fileio/naming-a-file (MAX_PATH is
#   defined as 260 characters)
MAX_PATH = 260

# source: ERROR_ACCESS_DENIED = 5, learn.microsoft.com/windows/win32/debug/
#   system-error-codes--0-499-
ERROR_ACCESS_DENIED = 5

# source: ERROR_NO_MORE_FILES = 18, learn.microsoft.com/windows/win32/debug/
#   system-error-codes--0-499-
ERROR_NO_MORE_FILES = 18

# source: ERROR_INVALID_PARAMETER = 87, learn.microsoft.com/windows/win32/debug/
#   system-error-codes--0-499-
ERROR_INVALID_PARAMETER = 87

# source: INVALID_HANDLE_VALUE is ``(HANDLE)~(ULONG_PTR)0`` (all bits set), as
#   declared in winbase.h and mirrored by Wine include/winbase.h
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class FileTime(ctypes.Structure):
    """``FILETIME``: two DWORDs forming a 64-bit count of 100 ns ticks."""

    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class ProcessEntry32W(ctypes.Structure):
    """``PROCESSENTRY32W``. Field semantics: learn.microsoft.com
    ``ns-tlhelp32-processentry32w``; field order and C types: Wine
    ``include/tlhelp32.h`` (the Microsoft page lists the fields without the
    C syntax block). ``th32DefaultHeapID`` is a ``ULONG_PTR``."""

    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


def bind_kernel32(dll: Any) -> Any:
    """Declare argtypes/restype of every kernel32 function used here.

    Without declarations ctypes passes 64-bit handles as 32-bit ints, which
    truncates them on Win64. postcondition: returns ``dll`` with each
    function typed; no call is made."""
    handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    ptr = ctypes.POINTER
    dll.OpenProcess.argtypes = [dword, boolean, dword]
    dll.OpenProcess.restype = handle
    dll.CloseHandle.argtypes = [handle]
    dll.CloseHandle.restype = boolean
    dll.GetExitCodeProcess.argtypes = [handle, ptr(dword)]
    dll.GetExitCodeProcess.restype = boolean
    dll.GetProcessTimes.argtypes = [
        handle,
        ptr(FileTime),
        ptr(FileTime),
        ptr(FileTime),
        ptr(FileTime),
    ]
    dll.GetProcessTimes.restype = boolean
    dll.CreateToolhelp32Snapshot.argtypes = [dword, dword]
    dll.CreateToolhelp32Snapshot.restype = handle
    dll.Process32FirstW.argtypes = [handle, ptr(ProcessEntry32W)]
    dll.Process32FirstW.restype = boolean
    dll.Process32NextW.argtypes = [handle, ptr(ProcessEntry32W)]
    dll.Process32NextW.restype = boolean
    return dll


@functools.lru_cache(maxsize=1)
def _kernel32() -> Any:
    """The bound kernel32, built once. Raises ``OSError`` off Windows (a caller bug:
    platform dispatch belongs to the caller)."""
    if sys.platform != "win32":
        raise OSError("win32_process is Windows-only")
    return bind_kernel32(ctypes.WinDLL("kernel32", use_last_error=True))


def _last_error() -> int:
    """``GetLastError`` of the last kernel32 call on this thread (saved by
    ``use_last_error=True``); like ``_kernel32``, refused off Windows."""
    if sys.platform != "win32":
        raise OSError("win32_process is Windows-only")
    return ctypes.get_last_error()


def pid_alive_with(dll: Any, pid: int) -> bool:
    """True iff ``pid`` names a process that has not terminated.

    precondition: ``pid > 0``. postcondition: ``OpenProcess`` denied access
    means the process exists (True, as ``PermissionError`` does on POSIX);
    ``ERROR_INVALID_PARAMETER`` means no such pid (False); otherwise True
    iff ``GetExitCodeProcess`` reports ``STILL_ACTIVE``; the handle is
    closed on every path. Any other failure raises ``OSError``: an unknown
    error must not be read as "dead". Caveat from the Microsoft page: a
    process that itself exited with code 259 reads as alive.

    source: ADR-1096"""
    handle = dll.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        error = _last_error()
        if error == ERROR_ACCESS_DENIED:
            return True
        if error == ERROR_INVALID_PARAMETER:
            return False
        raise OSError(error, "OpenProcess failed", pid)
    try:
        code = ctypes.c_uint32()
        if not dll.GetExitCodeProcess(handle, ctypes.pointer(code)):
            raise OSError(_last_error(), "GetExitCodeProcess failed", pid)
        return code.value == STILL_ACTIVE
    finally:
        dll.CloseHandle(handle)


def creation_filetime_with(dll: Any, pid: int) -> int | None:
    """Creation time of ``pid`` as a 64-bit FILETIME count, or None when the
    process does not exist or cannot be opened (access denied).

    postcondition: the same pid yields the same value for the process's whole
    life; a recycled pid yields a different one. Other failures raise
    ``OSError``. The handle is closed on every path.

    source: ADR-1096"""
    handle = dll.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        error = _last_error()
        if error in (ERROR_ACCESS_DENIED, ERROR_INVALID_PARAMETER):
            return None
        raise OSError(error, "OpenProcess failed", pid)
    try:
        created, exited, kernel, user = (FileTime() for _ in range(4))
        pointers = [ctypes.pointer(t) for t in (created, exited, kernel, user)]
        if not dll.GetProcessTimes(handle, *pointers):
            raise OSError(_last_error(), "GetProcessTimes failed", pid)
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        dll.CloseHandle(handle)


def snapshot_rows_with(dll: Any) -> list[ProcessRow]:
    """Every process in the system at one instant.

    postcondition: one row per process, in the OS order; the snapshot handle
    is closed on every path. The enumeration ends only on
    ``ERROR_NO_MORE_FILES``; any other terminating error raises ``OSError``
    (a truncated table would make the ancestor walk answer from partial
    data)."""
    snapshot = dll.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        raise OSError(_last_error(), "CreateToolhelp32Snapshot failed")
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        entry_ptr = ctypes.pointer(entry)
        rows: list[ProcessRow] = []
        more = dll.Process32FirstW(snapshot, entry_ptr)
        while more:
            rows.append(
                ProcessRow(
                    entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile
                )
            )
            more = dll.Process32NextW(snapshot, entry_ptr)
        error = _last_error()
        if error != ERROR_NO_MORE_FILES:
            raise OSError(error, "Process32FirstW/NextW ended abnormally")
        return rows
    finally:
        dll.CloseHandle(snapshot)


def pid_alive(pid: int) -> bool:
    """``pid_alive_with`` on the real kernel32 (win32 only)."""
    return pid_alive_with(_kernel32(), pid)


def creation_filetime(pid: int) -> int | None:
    """``creation_filetime_with`` on the real kernel32 (win32 only)."""
    return creation_filetime_with(_kernel32(), pid)


def snapshot_rows() -> list[ProcessRow]:
    """``snapshot_rows_with`` on the real kernel32 (win32 only)."""
    return snapshot_rows_with(_kernel32())
