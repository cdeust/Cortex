"""Filesystem-level mutual exclusion for pipeline_installer.

source: ADR-0586"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

from mcp_server.shared.platform import home_dir

_LOCK_FILE = home_dir() / ".claude" / "methodology" / ".install.lock"


class InstallLockBusyError(RuntimeError):
    """Raised when another install_pipeline holder owns the lock."""


@contextmanager
def install_lock() -> Iterator[None]:
    """Acquire the installation lock. Raises InstallLockBusyError immediately on
    contention.

        source: ADR-0586"""
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


if sys.platform == "win32":  # source: ADR-0586
    # source: ADR-0586
    import msvcrt

    def _acquire(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            os.close(fd)
            raise InstallLockBusyError(str(_LOCK_FILE)) from exc

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
            raise InstallLockBusyError(str(_LOCK_FILE)) from exc

    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            # Unlock is best-effort: closing the fd releases the lock anyway.
            pass
