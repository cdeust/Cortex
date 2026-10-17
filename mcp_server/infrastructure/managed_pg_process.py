"""Kernel facts the managed PostgreSQL lifecycle is decided by — stdlib, POSIX.

Nothing here reads a clock or retries:

- ``started(pid)``: the kernel's start time of ``pid`` (macOS ``proc_pidinfo``
  ``PROC_PIDTBSDINFO``; Linux field 22 of ``/proc/<pid>/stat``). A PID reused
  by another program has another start time, so ``(pid, started)`` names one
  process for its whole life, emulated (qemu, Rosetta) or not.
- ``alive_as_this_user(pid)``: ``kill(pid, 0)``; EPERM is another user's
  process, which is never this user's postmaster.
- ``Watch``: blocks until an entry of one directory changes or a pipe whose
  only writers are a process group reaches end of file, i.e. the group
  exited (macOS ``kqueue`` ``EVFILT_VNODE``/``EVFILT_READ``; Linux
  ``inotify`` and ``select``). No pidfd (absent under qemu-user, measured
  2026-10-17: ENOSYS) and no per-PID filter: the pipe is the exit event.
  The caller re-reads what it waits for after every wake-up.

source: ADR-1110
"""

from __future__ import annotations

import ctypes
import os
import select
import sys
from pathlib import Path

_PROC_PIDTBSDINFO = 3  # source: <sys/proc_info.h> (PROC_PIDTBSDINFO)
_STAT_STATE, _STAT_STARTTIME = 0, 19  # source: proc(5) fields 3 and 22, after "comm)"
_SZOMB = 5  # source: <sys/proc.h> SZOMB (pbi_status of an exited, unreaped process)
# source: <sys/inotify.h> IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM
# | IN_MOVED_TO | IN_CREATE | IN_DELETE
_IN_MASK = 0x2 | 0x4 | 0x8 | 0x40 | 0x80 | 0x100 | 0x200
_INOTIFY_READ = 65536  # source: inotify(7) (any size >= one event drains it)


class _BsdInfo(ctypes.Structure):
    """``struct proc_bsdinfo`` from <sys/proc_info.h>."""

    _fields_ = [  # noqa: RUF012 — ctypes reads this class attribute
        *((name, ctypes.c_uint32) for name in (
            "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid",
            "rgid", "svuid", "svgid", "rfu_1")),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        *((name, ctypes.c_uint32) for name in (
            "nfiles", "pgid", "pjobc", "e_tdev", "e_tpgid")),
        ("nice", ctypes.c_int32),
        ("start_tvsec", ctypes.c_uint64),
        ("start_tvusec", ctypes.c_uint64),
    ]  # fmt: skip


def started(pid: int) -> str | None:
    """The kernel's start time of ``pid``, ``None`` when it has none: no such
    process, another user's, or a zombie (it exited; only its parent's
    ``wait`` keeps the entry, as in a container without an init process)."""
    if sys.platform == "darwin":
        info = _BsdInfo()
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        size = ctypes.sizeof(info)
        got = libproc.proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, ctypes.byref(info), size)
        if got != size or info.status == _SZOMB:
            return None
        return f"{info.start_tvsec}.{info.start_tvusec:06d}"
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except OSError:
        return None
    fields = stat.rpartition(")")[2].split()
    return None if fields[_STAT_STATE] == "Z" else fields[_STAT_STARTTIME]


def exited(exit_fd: int) -> bool:
    """Whether every writer of the pipe ``exit_fd`` closed it, i.e. the group
    holding its write end exited. Never blocks: a zero-timeout ``select``
    reads the state, it decides nothing by time."""
    readable, _, _ = select.select([exit_fd], [], [], 0)
    return bool(readable) and os.read(exit_fd, 1) == b""


def alive_as_this_user(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # another user's process: never this cluster's postmaster
    return True


if sys.platform == "darwin":

    class Watch:
        """kqueue: vnode events on the directory and followed files, and a
        read event on ``exit_fd`` (end of file once the process group exited)."""

        def __init__(self, directory: Path, exit_fd: int) -> None:
            self._kq = select.kqueue()
            self._fds: dict[Path, int] = {}
            self.follow(directory)
            flags = select.KQ_EV_ADD | select.KQ_EV_CLEAR
            self._kq.control([select.kevent(exit_fd, select.KQ_FILTER_READ, flags)], 0)

        def follow(self, path: Path) -> None:
            """Also wake on writes to ``path`` (a directory: on entry changes);
            a path replaced by another file is followed anew."""
            try:
                fd = os.open(path, os.O_RDONLY)
            except FileNotFoundError:
                return
            known = self._fds.get(path)
            if known is not None and os.fstat(known).st_ino == os.fstat(fd).st_ino:
                os.close(fd)
                return
            if known is not None:
                os.close(known)
            self._fds[path] = fd
            fflags = (
                select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE
            )
            flags = select.KQ_EV_ADD | select.KQ_EV_CLEAR
            vnode = select.KQ_FILTER_VNODE
            event = select.kevent(fd, vnode, flags, fflags | select.KQ_NOTE_RENAME)
            self._kq.control([event], 0)

        def wait(self) -> None:
            self._kq.control(None, 1)

        def close(self) -> None:
            for fd in self._fds.values():
                os.close(fd)
            self._kq.close()

else:

    class Watch:
        """inotify on the directory (its files included) and ``exit_fd``."""

        def __init__(self, directory: Path, exit_fd: int) -> None:
            libc = ctypes.CDLL(None, use_errno=True)
            self._exit_fd = exit_fd
            self._inotify = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if self._inotify < 0:
                raise OSError(ctypes.get_errno(), "inotify_init1")
            if libc.inotify_add_watch(self._inotify, bytes(directory), _IN_MASK) < 0:
                os.close(self._inotify)
                raise OSError(ctypes.get_errno(), f"inotify_add_watch {directory}")

        def follow(self, path: Path) -> None:
            """Files in the watched directory already wake ``wait``."""

        def wait(self) -> None:
            select.select([self._inotify, self._exit_fd], [], [])
            try:
                os.read(self._inotify, _INOTIFY_READ)
            except BlockingIOError:
                pass  # the wake-up was the exit, not the directory

        def close(self) -> None:
            os.close(self._inotify)


def watch(directory: Path, exit_fd: int) -> Watch:
    """Wake on a change under ``directory`` or once ``exit_fd`` (the read end
    of a pipe whose only writers are a process group) reaches end of file;
    the caller re-reads what it waits for after every wake-up. ``close`` it."""
    return Watch(directory, exit_fd)
