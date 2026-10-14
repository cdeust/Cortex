"""Interprocess file locks for the launcher's installs — stdlib only.

An OS lock (``flock`` on POSIX, ``msvcrt.locking`` on Windows) is released by
the kernel when its holder exits, killed or not, so a lock never goes stale
and is never broken by age: a waiter waits while the holder lives. Waiting
has a bound, and reaching it is an error that names the lock, never a reason
to proceed unlocked.

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from typing import Iterator

_POLL_SECONDS = 0.2  # source: ADR-0747 (the poll interval of the lock this replaces)


class LockTimeoutError(RuntimeError):
    """Another process held the lock for longer than the caller would wait."""


if sys.platform == "win32":  # source: ADR-0586 (same primitive, pipeline_install_lock)
    import msvcrt

    def _try(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

else:
    import fcntl

    def _try(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def _open(path: str) -> int:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o644)


@contextlib.contextmanager
def held(path: str, wait_seconds: float) -> Iterator[None]:
    """Hold ``path`` exclusively, waiting at most ``wait_seconds`` for it.

    Raises ``LockTimeoutError`` when the holder keeps it past the bound.
    """
    fd = _open(path)
    try:
        deadline = time.monotonic() + wait_seconds
        while not _try(fd):
            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"{path} is still held by another Cortex process after "
                    f"{wait_seconds:.0f} s"
                )
            time.sleep(_POLL_SECONDS)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


@contextlib.contextmanager
def held_if_free(path: str) -> Iterator[bool]:
    """Hold ``path`` when no one else does; yield whether it is held."""
    fd = _open(path)
    try:
        yield _try(fd)
    finally:
        os.close(fd)
