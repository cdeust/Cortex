"""Serialize cooperating log writers across processes and threads.

source: ADR-0654"""

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
    """Hold an interprocess lock using a persistent sidecar file.

    source: ADR-0654
    """
    # source: ADR-0654
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
        # source: ADR-0654

        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)

    def _release(descriptor: int) -> None:
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(descriptor: int) -> None:
        # source: ADR-0654
        fcntl.flock(descriptor, fcntl.LOCK_EX)

    def _release(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
