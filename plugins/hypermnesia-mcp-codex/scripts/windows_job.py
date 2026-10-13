"""Creation flags for the detached drain on Windows, from the measured job.

The Codex intake is standard-library only and ships without mcp_server
(ADR-1084), so this repeats mcp_server.shared.win32_job and detached_spawn with
ctypes: the same probe, the same decision, decided once, never retried. A test
keeps the decision table, the structure layout and the real probe equal to
mcp_server's.

source: ADR-1102"""

from __future__ import annotations

import ctypes
import sys

# source: Microsoft page process-creation-flags (CREATE_NEW_PROCESS_GROUP,
#   CREATE_NO_WINDOW, CREATE_BREAKAWAY_FROM_JOB rows), as in detached_spawn
CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW = 0x00000200, 0x08000000
# source: same page (CREATE_BREAKAWAY_FROM_JOB row), as in detached_spawn
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
# source: Microsoft page JOBOBJECT_BASIC_LIMIT_INFORMATION (LimitFlags), as in
#   win32_job
BREAKAWAY_OK, SILENT_BREAKAWAY_OK, KILL_ON_JOB_CLOSE = 0x800, 0x1000, 0x2000
# source: Microsoft page QueryInformationJobObject (JobObjectExtendedLimitInformation)
_EXTENDED_LIMIT_INFORMATION = 9

_BASE_FLAGS = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW


class BasicLimits(ctypes.Structure):
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
    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def creationflags(job_limit_flags):
    """The detached drain's flags; breakaway only where the job accepts it."""
    if job_limit_flags is None or job_limit_flags & SILENT_BREAKAWAY_OK:
        return _BASE_FLAGS
    if job_limit_flags & BREAKAWAY_OK:
        return _BASE_FLAGS | CREATE_BREAKAWAY_FROM_JOB
    return _BASE_FLAGS


def bind_kernel32(dll):
    handle, boolean = ctypes.c_void_p, ctypes.c_int32
    dll.GetCurrentProcess.argtypes = []
    dll.GetCurrentProcess.restype = handle
    dll.IsProcessInJob.argtypes = [handle, handle, ctypes.POINTER(boolean)]
    dll.IsProcessInJob.restype = boolean
    dll.QueryInformationJobObject.argtypes = [
        handle,
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    dll.QueryInformationJobObject.restype = boolean
    return dll


def _last_error():
    return ctypes.get_last_error()


def _win32_error(call):
    code = _last_error()
    return OSError(0, f"{call} failed (Windows error {code})", None, code)


def job_limit_flags_with(dll):
    """LimitFlags of this process's immediate job, None outside any job; an
    unreadable job state raises OSError, never reads as "no job"."""
    in_job = ctypes.c_int32()
    if not dll.IsProcessInJob(dll.GetCurrentProcess(), None, ctypes.byref(in_job)):
        raise _win32_error("IsProcessInJob")
    if not in_job.value:
        return None
    limits = ExtendedLimits()
    if not dll.QueryInformationJobObject(
        None,
        _EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
        None,
    ):
        raise _win32_error("QueryInformationJobObject")
    return int(limits.BasicLimitInformation.LimitFlags)


def job_limit_flags():
    if sys.platform != "win32":
        raise OSError("windows_job is Windows-only")
    return job_limit_flags_with(
        bind_kernel32(ctypes.WinDLL("kernel32", use_last_error=True))
    )


def measured_creationflags():
    """Measure the job once and decide; report a child that dies with it."""
    flags = job_limit_flags()
    if flags is not None and not flags & (BREAKAWAY_OK | SILENT_BREAKAWAY_OK):
        if flags & KILL_ON_JOB_CLOSE:
            print(
                f"[cortex SessionEnd] drain stays in the caller's job "
                f"(LimitFlags=0x{flags:x}: no breakaway allowed, kill on job "
                "close); it ends when the job closes",
                file=sys.stderr,
            )
    return creationflags(flags)
