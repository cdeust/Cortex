"""Durable file spool for capture payloads on platforms without the resident worker.

The hook only writes a file here and starts a detached drainer; the drainer
(``mcp_server.hooks.capture_drain``) stores the files. Nothing in this module
needs ``AF_UNIX``, ``fcntl`` or ``geteuid``, so it runs on Windows. Its lock
is the kernel's (``msvcrt.locking`` / ``fcntl.flock``): a crashed drainer
releases it with its process, so no stale-lock recovery exists or is needed.

source: ADR-1094
"""

from __future__ import annotations

import errno
import json
import os
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# source: ADR-1084 (private directory under the configured Cortex root, mode 0700
# where the platform has modes; on Windows it inherits the user-profile ACL)
PRIVATE_DIR = 0o700
# source: ADR-0486 (the worker's own private ``.capture-worker`` directory)
SPOOL_ROOT = ".capture-worker"
REJECTED_SUFFIX = ".rejected"
_PAYLOAD_SUFFIX = ".json"
# source: https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking
# (``msvcrt.locking`` locks ``nbytes`` from the current position; one byte is
# the minimum that carries a lock)
_LOCK_BYTES = 1


def spool_directory(root: Path) -> Path:
    """postcondition: ``<root>/.capture-worker/spool`` exists; its path is returned."""
    root = root.expanduser().absolute()
    spool = root / SPOOL_ROOT / "spool"
    # one level at a time: ``mkdir(parents=True)`` applies ``mode`` to the leaf only
    for directory in (root, spool.parent, spool):
        directory.mkdir(mode=PRIVATE_DIR, exist_ok=True)
    return spool


def error_log(spool: Path) -> BinaryIO:
    """Append-only stream for the drainer's raw stdout/stderr (``drain.err``).

    Holds only what happens before the drainer's own rotating log exists or
    outside it (an import failure, an interpreter crash): empty when all is well."""
    descriptor = os.open(
        spool.parent / "drain.err", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
    )
    return os.fdopen(descriptor, "ab")


def write(spool: Path, payload: dict[str, object]) -> Path:
    """precondition: ``payload`` is JSON-serialisable.
    postcondition: one complete ``*.json`` file holds ``payload``; a reader never
    sees a partial one (written under another suffix, then ``os.replace``d)."""
    name = f"{time.time_ns():020d}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    partial = spool / f".{name}.partial"
    target = spool / f"{name}{_PAYLOAD_SUFFIX}"
    partial.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(partial, target)
    return target


def pending(spool: Path) -> list[Path]:
    """Complete payload files in name order: write time first, so oldest first up to
    the clock's resolution; captures are independent, ties need no order."""
    return sorted(spool.glob(f"*{_PAYLOAD_SUFFIX}"))


def read(path: Path) -> dict[str, object]:
    """Raises ``OSError`` or ``ValueError`` on an unreadable or non-object file."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"capture spool file is not a JSON object: {path.name}")
    return value


def reject(path: Path) -> Path:
    """Keep a refused file for inspection; it no longer matches ``pending``."""
    target = path.with_name(path.name + REJECTED_SUFFIX)
    os.replace(path, target)
    return target


@contextmanager
def drain_lock(spool: Path) -> Iterator[bool]:
    """Non-blocking exclusive drainer lock; yields whether this process holds it.

    postcondition: at most one process yields True at a time; a lost race
    yields False at once (never waits), any other ``OSError`` propagates."""
    descriptor = os.open(spool.parent / "drain.lock", os.O_RDWR | os.O_CREAT, 0o600)
    held = False
    try:
        held = _try_lock(descriptor)
        yield held
    finally:
        if held and sys.platform == "win32":
            # Windows frees the locks of a closed handle asynchronously; unlock
            # explicitly so the next acquisition (the drainer's rescan) sees it free.
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, _LOCK_BYTES)
        os.close(descriptor)


def _try_lock(descriptor: int) -> bool:
    try:
        if sys.platform == "win32":
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, _LOCK_BYTES)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno not in {errno.EAGAIN, errno.EACCES}:
            raise
        return False
    return True
