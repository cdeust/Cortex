"""The ``Popen`` options that start a child detached from the calling process.

Layer: shared. CPython ignores ``start_new_session`` on Windows, so a child
spawned with it alone keeps the hook's console and process group there.
``windows_creationflags`` is a pure decision over the measured job state, so
macOS and Linux test every Windows branch; ``options`` measures the job (win32
only) and applies it. The flags are decided once: no spawn is retried with
other flags.

source: ADR-1102"""

from __future__ import annotations

import logging
import sys
from typing import Any

from mcp_server.shared import win32_job

logger = logging.getLogger(__name__)

# The ``subprocess.*`` names of these flags exist only on Windows, so the
# documented values are spelled out to keep the decision testable everywhere.
# source: the Microsoft page process-creation-flags (learn.microsoft.com/
#   windows/win32/procthread); this one: not signalled with the parent's group
CREATE_NEW_PROCESS_GROUP = 0x00000200
# No console window; console children of the child share its hidden console.
# Ignored with DETACHED_PROCESS, which would make each console grandchild open
# a visible window of its own.
# source: same page as CREATE_NEW_PROCESS_GROUP (CREATE_NO_WINDOW row)
CREATE_NO_WINDOW = 0x08000000
# source: same page as CREATE_NEW_PROCESS_GROUP (requires the caller's job to
#   set JOB_OBJECT_LIMIT_BREAKAWAY_OK; no effect outside a job)
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

_BASE_FLAGS = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW


def windows_creationflags(job_limit_flags: int | None) -> int:
    """Creation flags for a detached child, given the caller's job limits.

    No job, or a job that lets children leave silently: the base flags. A job
    that sets ``BREAKAWAY_OK``: the child asks to leave it. A job that allows
    neither: the base flags, because asking would make ``CreateProcess`` fail;
    the child stays in the job and lives as long as the job lets it."""
    if job_limit_flags is None:
        return _BASE_FLAGS
    if job_limit_flags & win32_job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK:
        return _BASE_FLAGS
    if job_limit_flags & win32_job.JOB_OBJECT_LIMIT_BREAKAWAY_OK:
        return _BASE_FLAGS | CREATE_BREAKAWAY_FROM_JOB
    return _BASE_FLAGS


def platform_options(platform: str, job_limit_flags: int | None) -> dict[str, Any]:
    """``Popen`` keyword arguments that detach the child on ``platform``.

    postcondition: POSIX gets a new session (``start_new_session``); win32
    gets ``creationflags`` only, since ``start_new_session`` is ignored there."""
    if platform == "win32":
        return {"creationflags": windows_creationflags(job_limit_flags)}
    return {"start_new_session": True}


def _warn_if_job_bound(job_limit_flags: int | None) -> None:
    """Say so when the child cannot leave a job that kills it on close."""
    may_leave = (
        win32_job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
        | win32_job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    )
    if job_limit_flags is None or job_limit_flags & may_leave:
        return
    if job_limit_flags & win32_job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE:
        logger.warning(
            "detached child stays in the caller's job (LimitFlags=0x%x: no "
            "breakaway allowed, kill on job close); it ends when the job closes",
            job_limit_flags,
        )


def options() -> dict[str, Any]:
    """``platform_options`` for this process: on win32 the job is measured
    (``win32_job.job_limit_flags``, which raises ``OSError`` when it cannot be
    read) and a job-bound child is reported before the spawn."""
    if sys.platform != "win32":
        return platform_options(sys.platform, None)
    job_limit_flags = win32_job.job_limit_flags()
    _warn_if_job_bound(job_limit_flags)
    return platform_options(sys.platform, job_limit_flags)
