"""Filesystem-level mutual exclusion for pipeline_installer.

Prevents concurrent setup.sh runs (or a SessionStart auto-install racing
the user's manual setup) from corrupting the shared install state:
half-cloned src/, racy symlink swap, JSON config truncation.

Non-blocking acquire — contended runs return immediately so callers can
surface a clear ``install_in_progress`` action rather than hanging the
user's terminal for 6 minutes.

POSIX uses ``fcntl.flock`` (advisory lock). Windows has no ``fcntl`` — its
import alone would crash this module at load on every Windows install — so
we use ``msvcrt.locking`` (mandatory byte-range lock) there. Both back the
same ``install_lock()`` contract; the only visible difference (advisory vs
mandatory) is immaterial because every caller goes through this function.

source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.4
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

from mcp_server.shared.platform import home_dir

_LOCK_FILE = home_dir() / ".claude" / "methodology" / ".install.lock"


class InstallLockBusy(RuntimeError):
    """Raised when another install_pipeline holder owns the lock."""


@contextmanager
def install_lock() -> Iterator[None]:
    """Acquire an exclusive non-blocking lock on the install file.

    Raises ``InstallLockBusy`` immediately on contention so callers can
    return a structured ``install_in_progress`` action instead of
    blocking for the duration of someone else's 6-minute build.

    We never read or write content — only the lock metadata matters. The fd
    stays open for the duration of the context to keep the lock held.
    """
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(_LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _acquire(fd)
        try:
            yield
        finally:
            _release(fd)
    finally:
        try:
            os.close(fd)
        except OSError:
            # fd already closed (e.g. by a failed _acquire); nothing to release.
            pass


if sys.platform == "win32":  # == shared.platform.IS_WINDOWS; literal so the checker
    # resolves the msvcrt/fcntl split per-platform instead of flagging both.
    import msvcrt

    def _acquire(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            os.close(fd)
            raise InstallLockBusy(str(_LOCK_FILE)) from exc

    def _release(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            # Unlock is best-effort: closing the fd releases the lock anyway.
            pass

else:
    import fcntl

    def _acquire(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise InstallLockBusy(str(_LOCK_FILE)) from exc

    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            # Unlock is best-effort: closing the fd releases the lock anyway.
            pass
