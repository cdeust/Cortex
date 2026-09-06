"""Short counter transactions using a stable cross-platform lock file.

Like pipeline_install_lock, the lock is separate from replaceable JSON.
Acquisition waits only for a filesystem counter transaction; callers must
never run models, DB operations, or the cascade while holding it.

source: https://docs.python.org/3/library/fcntl.html#fcntl.flock
source: https://docs.python.org/3/library/msvcrt.html#msvcrt.locking
Windows LK_LOCK uses the CRT's documented retry policy; errors propagate.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def counter_lock(path: Path) -> Iterator[None]:
    """Serialize read/modify/replace without dropping contending ticks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # source: POSIX owner read/write bits; no session-state access for peers.
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _acquire(fd)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


if sys.platform == "win32":
    import msvcrt

    def _acquire(fd: int) -> None:
        # source: msvcrt locks a byte range, including beyond end of file.
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _release(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
