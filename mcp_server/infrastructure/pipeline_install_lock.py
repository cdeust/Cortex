"""Filesystem-level mutual exclusion for pipeline_installer.

Prevents concurrent setup.sh runs (or a SessionStart auto-install racing
the user's manual setup) from corrupting the shared install state:
half-cloned src/, racy symlink swap, JSON config truncation.

Uses fcntl.flock (POSIX advisory lock). Non-blocking acquire — contended
runs return immediately so callers can surface a clear ``install_in_progress``
action rather than hanging the user's terminal for 6 minutes.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_LOCK_FILE = Path.home() / ".claude" / "methodology" / ".install.lock"


class InstallLockBusy(RuntimeError):
    """Raised when another install_pipeline holder owns the lock."""


@contextmanager
def install_lock() -> Iterator[None]:
    """Acquire an exclusive non-blocking lock on the install file.

    Raises ``InstallLockBusy`` immediately on contention so callers can
    return a structured ``install_in_progress`` action instead of
    blocking for the duration of someone else's 6-minute build.

    The lock file is opened in append mode so concurrent acquires don't
    truncate it; we never read or write content — only the lock metadata
    matters. The fd stays open for the duration of the context to keep
    the lock held.
    """
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(_LOCK_FILE), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise InstallLockBusy(str(_LOCK_FILE)) from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
    finally:
        try:
            os.close(fd)
        except Exception:
            pass
