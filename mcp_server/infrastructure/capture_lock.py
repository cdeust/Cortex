"""Deadline-bound launch-lock wait without polling or a busy spin.

source: ADR-0509"""

from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

from mcp_server.infrastructure.capture_transport import remaining

if sys.platform != "win32":
    import fcntl


def _acquire(descriptor: int, result: Future[None]) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        if result.set_running_or_notify_cancel():
            result.set_exception(exc)
    else:
        if result.set_running_or_notify_cancel():
            result.set_result(None)
    finally:
        os.close(descriptor)


def wait_for_lock(descriptor: int, deadline: float) -> None:
    result: Future[None] = Future()
    duplicate = os.dup(descriptor)
    waiter = threading.Thread(target=_acquire, args=(duplicate, result), daemon=True)
    try:
        waiter.start()
    except RuntimeError:
        os.close(duplicate)
        raise
    try:
        result.result(timeout=remaining(deadline))
    # source: ADR-0509
    except (FutureTimeoutError, TimeoutError):
        if result.cancel():
            raise TimeoutError("capture launch lock deadline exceeded") from None
        # RUNNING means flock already returned: only publication remains.
        result.result()
