"""One consolidation cycle at a time across every process on this machine.

Three entry points start a cycle on their own: SessionStart's
``consolidate_background`` worker, SessionEnd's ``session_lifecycle
--consolidate`` worker (one per ending session) and the MCP ``consolidate``
tool. Nothing serialised them: on 2026-10-21 two ``session_lifecycle
--consolidate`` processes were alive at once for 1 h 26 and 2 h 50
(docs/verification/connection-broker/experiment-log.md entry 7). A
non-blocking kernel file lock makes a second caller skip instead of piling
on; the kernel releases it when its holder exits, killed or not. A file lock
rather than ``pg_try_advisory_lock``: a session advisory lock would pin a
database connection for the whole cycle.

Idea and first implementation: commit 4dc9f66e (worktree
fix-idle-tx-pileup, Claude session 01BxsVCVscNG2Vb7fafCgqYR); this module is
the same design written for this branch.

source: ADR-1112 (lock pattern of pipeline_install_lock, ADR-0586)
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from mcp_server.infrastructure.config import METHODOLOGY_DIR

# source: ADR-1112 under METHODOLOGY_DIR, which honours CORTEX_CLAUDE_DIR
LOCK_PATH = METHODOLOGY_DIR / ".consolidate.lock"
# source: Unix owner read/write only (same rule as capture_socket, ADR-0512)
_PRIVATE_FILE = 0o600


@contextmanager
def consolidate_single_flight() -> Iterator[bool]:
    """Yield True when this process holds the lock, False when another does."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(LOCK_PATH), os.O_RDWR | os.O_CREAT, _PRIVATE_FILE)
    held = False
    try:
        held = _try_acquire(descriptor)
        yield held
    finally:
        if held:
            _release(descriptor)
        os.close(descriptor)


if sys.platform == "win32":  # source: ADR-0586
    import msvcrt

    def _try_acquire(descriptor: int) -> bool:
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _release(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_acquire(descriptor: int) -> bool:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _release(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
