"""Serialize cooperating log writers across processes and threads.

FileHandler locks are thread-local, not interprocess (Python Logging Cookbook,
https://docs.python.org/3/howto/logging-cookbook.html). Use one stable sidecar
inode so renaming the data file cannot detach the lock from other writers.
The lock covers rotate/open/write or Popen, never the worker's runtime.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_THREAD_LOCK = threading.Lock()


@contextmanager
def log_file_lock(path: Path) -> Iterator[None]:
    """Keep the sidecar: unlinking it would split concurrent lock holders."""
    # source: owner-only permission for the lock metadata; os.open mode contract.
    descriptor = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        with _THREAD_LOCK:
            _acquire(descriptor)
            try:
                yield
            finally:
                _release(descriptor)
    finally:
        os.close(descriptor)


if sys.platform == "win32":
    import msvcrt

    def _acquire(descriptor: int) -> None:
        # source: https://docs.python.org/3/library/msvcrt.html#msvcrt.locking
        # One shared byte is sufficient; locking beyond EOF is supported.
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)

    def _release(descriptor: int) -> None:
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(descriptor: int) -> None:
        # source: https://docs.python.org/3/library/fcntl.html#fcntl.flock
        fcntl.flock(descriptor, fcntl.LOCK_EX)

    def _release(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
