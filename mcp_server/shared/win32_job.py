"""The Windows job object the current process runs in, over ``ctypes`` (kernel32).

Layer: shared (stdlib only). A detached spawn needs to know whether the
calling process sits in a job and which limits that job sets: a job may kill
its processes when its last handle closes, and only a job that sets
``JOB_OBJECT_LIMIT_BREAKAWAY_OK`` accepts a child created with
``CREATE_BREAKAWAY_FROM_JOB`` (any other job makes ``CreateProcess`` fail).
This module reports that state; ``detached_spawn`` decides the flags from it.
The logic runs everywhere against a fake kernel32; the real kernel32 only on
``win32``.

source: ADR-1102"""

from __future__ import annotations

import ctypes
import functools
import sys
from typing import Any

# source: learn.microsoft.com/windows/win32/api/winnt/
#   ns-winnt-jobobject_basic_limit_information (LimitFlags values)
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
# source: same page as JOB_OBJECT_LIMIT_BREAKAWAY_OK
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
# source: same page as JOB_OBJECT_LIMIT_BREAKAWAY_OK
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

# source: the information-class table of QueryInformationJobObject, learn.
#   microsoft.com/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class BasicLimits(ctypes.Structure):
    """``JOBOBJECT_BASIC_LIMIT_INFORMATION`` (winnt.h), field order and C types
    from the Microsoft page; ``LARGE_INTEGER`` is a signed 64-bit integer."""

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class IoCounters(ctypes.Structure):
    """``IO_COUNTERS`` (winnt.h): six ``ULONGLONG`` counters."""

    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class ExtendedLimits(ctypes.Structure):
    """``JOBOBJECT_EXTENDED_LIMIT_INFORMATION`` (winnt.h). The breakaway and
    kill-on-close limits "require use of" this structure (Microsoft page of the
    basic structure), so the query reads it rather than the basic one."""

    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def bind_kernel32(dll: Any) -> Any:
    """Declare argtypes/restype of the three kernel32 functions used here, so a
    64-bit handle is not truncated to a 32-bit int. No call is made."""
    handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    dll.GetCurrentProcess.argtypes = []
    dll.GetCurrentProcess.restype = handle
    dll.IsProcessInJob.argtypes = [handle, handle, ctypes.POINTER(boolean)]
    dll.IsProcessInJob.restype = boolean
    dll.QueryInformationJobObject.argtypes = [
        handle,
        ctypes.c_int32,
        ctypes.c_void_p,
        dword,
        ctypes.POINTER(dword),
    ]
    dll.QueryInformationJobObject.restype = boolean
    return dll


@functools.lru_cache(maxsize=1)
def _kernel32() -> Any:
    """The bound kernel32, built once; refused off Windows (platform dispatch
    belongs to the caller)."""
    if sys.platform != "win32":
        raise OSError("win32_job is Windows-only")
    return bind_kernel32(ctypes.WinDLL("kernel32", use_last_error=True))


def _last_error() -> int:
    if sys.platform != "win32":
        raise OSError("win32_job is Windows-only")
    return ctypes.get_last_error()


def _win32_error(call: str) -> OSError:
    """The failed call's last error as ``winerror``, never as ``errno``.

    source: Python docs, built-in exceptions, OSError: "Under Windows, if the
    winerror constructor argument is an integer, the errno attribute is
    determined from the Windows error code, and the errno argument is
    ignored." The code is also in the message for other platforms' fakes."""
    code = _last_error()
    return OSError(0, f"{call} failed (Windows error {code})", None, code)


def job_limit_flags_with(dll: Any) -> int | None:
    """``LimitFlags`` of the job the current process runs in, or None when it
    runs in no job.

    postcondition: with a NULL job handle ``IsProcessInJob`` tests "any job" and
    ``QueryInformationJobObject`` reads the immediate job of the caller (both
    per the Microsoft pages). A failure of either call raises ``OSError``: an
    unknown job state is never read as "no job"."""
    in_job = ctypes.c_int32()
    if not dll.IsProcessInJob(dll.GetCurrentProcess(), None, ctypes.byref(in_job)):
        raise _win32_error("IsProcessInJob")
    if not in_job.value:
        return None
    limits = ExtendedLimits()
    if not dll.QueryInformationJobObject(
        None,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
        None,
    ):
        raise _win32_error("QueryInformationJobObject")
    return int(limits.BasicLimitInformation.LimitFlags)


def job_limit_flags() -> int | None:
    """``job_limit_flags_with`` on the real kernel32 (win32 only)."""
    return job_limit_flags_with(_kernel32())
