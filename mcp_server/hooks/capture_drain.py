"""Detached drainer of the capture spool: the store path where no worker can run.

``capture_dispatch`` writes each admitted payload to the spool and starts this
process without waiting. Whichever drainer wins the non-blocking lock stores
every pending file through ``capture_store.store`` (the handler, imported and
loaded once for the whole burst); the others exit at once. After releasing the
lock the winner scans once more, so a file written between its last scan and the
release is never stranded (its own drainer lost the lock and exited).

Delivery is at-least-once: a file is deleted only after ``store`` returned, and a
replay after a crash is absorbed by the write gate's duplicate detection.
A refused or failing payload is renamed ``*.rejected`` (kept for inspection) and
reported as ``capture_skipped``; nothing is swallowed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit
from mcp_server.hooks.capture_dispatch import report_failure
from mcp_server.hooks.capture_store import store
from mcp_server.hooks.capture_worker_logging import LOG_BYTES
from mcp_server.infrastructure import capture_spool
from mcp_server.infrastructure.config import CLAUDE_DIR

logger = logging.getLogger(__name__)


async def drain_pending(spool: Path) -> int:
    """precondition: the caller holds ``capture_spool.drain_lock``.
    postcondition: every file that was pending is either stored and deleted, or
    renamed ``*.rejected`` after a ``capture_skipped`` report; returns the
    number stored."""
    stored = 0
    for path in capture_spool.pending(spool):
        started = time.monotonic()
        try:
            await store(capture_spool.read(path))
        except Exception as exc:  # noqa: BLE001 — per-file boundary: a refused or failing payload must not strand the files behind it; it is reported and kept as *.rejected
            elapsed = time.monotonic() - started
            rejected = capture_spool.reject(path)
            report_failure(
                f"capture rejected after {elapsed:.3f}s ({rejected.name}): "
                f"{type(exc).__name__}: {exc}",
                elapsed,
            )
            continue
        path.unlink()
        stored += 1
    return stored


def drain(spool: Path) -> None:
    """Drain until a scan taken after releasing the lock finds nothing.

    invariant: each pass either returns or consumed at least one file (stored or
    renamed), so the loop ends; a lost lock returns immediately."""
    while True:
        with capture_spool.drain_lock(spool) as held:
            if not held:
                return
            asyncio.run(drain_pending(spool))
        if not capture_spool.pending(spool):
            return


def main() -> None:
    spool = capture_spool.spool_directory(CLAUDE_DIR)
    # source: ADR-0488 (private rotating diagnostics, same budget as the worker's)
    handler = RotatingFileHandler(
        spool.parent / "drain.log", maxBytes=LOG_BYTES, backupCount=1, encoding="utf-8"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    with close_shared_store_on_exit():
        drain(spool)


if __name__ == "__main__":
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    main()
