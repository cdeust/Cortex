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
from pathlib import Path

from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit
from mcp_server.hooks.capture_dispatch import report_failure
from mcp_server.hooks.capture_store import store
from mcp_server.infrastructure import capture_spool
from mcp_server.infrastructure.config import CLAUDE_DIR


def _refuse(path: Path, exc: BaseException, elapsed: float) -> bool:
    """Retire a file that could not be stored and report it once.

    postcondition: returns True when the file no longer matches ``pending``.
    Normally it is renamed ``*.rejected``. If even that fails (a broken
    filesystem), the file is deleted so it cannot be replayed by every later
    drainer; if that fails too it stays and the caller skips it for this run.
    Every outcome is part of the one ``capture_skipped`` report."""
    detail = f"{type(exc).__name__}: {exc}"
    resolved = True
    try:
        fate = capture_spool.reject(path).name
    except OSError as rename_error:
        try:
            path.unlink(missing_ok=True)
            fate = f"deleted, rename failed: {rename_error}"
        except OSError as delete_error:
            resolved = False
            fate = f"left in place, rename and delete failed: {delete_error}"
    report_failure(f"capture rejected after {elapsed:.3f}s ({fate}): {detail}", elapsed)
    return resolved


async def drain_pending(spool: Path, skip: set[Path]) -> int:
    """precondition: the caller holds ``capture_spool.drain_lock``.
    postcondition: every pending file not in ``skip`` is stored and deleted, or
    retired by ``_refuse`` (added to ``skip`` when it could not be); a store that
    exceeds ``capture_spool.STORE_SECONDS`` is cancelled and refused like any
    failure. Returns the number stored."""
    stored = 0
    for path in capture_spool.pending(spool):
        if path in skip:
            continue
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                store(capture_spool.read(path)), capture_spool.STORE_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 — per-file boundary: a refused, failing or hung payload must not strand the files behind it; it is reported and retired
            if not _refuse(path, exc, time.monotonic() - started):
                skip.add(path)
            continue
        path.unlink()
        stored += 1
    return stored


def drain(spool: Path) -> None:
    """Drain until a scan taken after releasing the lock finds nothing new.

    invariant: each pass stores, retires or skips every file it sees, so the
    loop ends; a lost lock returns immediately."""
    skip: set[Path] = set()
    while True:
        with capture_spool.drain_lock(spool) as held:
            if not held:
                return
            asyncio.run(drain_pending(spool, skip))
            capture_spool.sweep(spool, time.time())
        if not [p for p in capture_spool.pending(spool) if p not in skip]:
            return


def main() -> None:
    spool = capture_spool.spool_directory(CLAUDE_DIR)
    # the single log is this process's stderr (see ``capture_spool.open_log``)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    with close_shared_store_on_exit():
        drain(spool)


if __name__ == "__main__":
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    main()
