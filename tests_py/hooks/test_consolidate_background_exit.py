"""Reproduces issue #398: consolidate_background never exits after a
successful cycle because the pooled store's non-daemon worker thread
outlives sys.exit().

Uses a real non-daemon ``threading.Thread`` as a stand-in for
``psycopg_pool.ConnectionPool``'s worker thread — the actual mechanism that
kept the reported process alive at ~98% CPU for 9 hours (issue #398). Each
case runs the REAL ``mcp_server/hooks/consolidate_background.py`` module as
``__main__`` (via ``runpy``, inside a forked child process) so the assertion
covers the shipped ``if __name__ == "__main__":`` wiring, not a stand-in for
it. The "unfixed" case simulates pre-fix behaviour by patching
``close_shared_store_on_exit`` to a no-op — the module's own lazy
``from ... import close_shared_store_on_exit`` then picks up the no-op,
reproducing exactly what the code did before this fix (call main(), never
close the store). Runs as a genuine OS process via ``multiprocessing``
(fork context, so the parent's already-patched module state is inherited
directly — no pickling, no re-import) so the assertion is about real
process lifecycle, not a mock of it.

precondition: none — the fake store never touches a real database.
postcondition (fixed case): the child process is reaped within the bound
and exits 0. postcondition (unfixed-simulation case): the child process is
NOT reaped within the bound — it demonstrably hangs, the same failure the
issue reports.
"""

from __future__ import annotations

import multiprocessing
import runpy
import threading
import time
from contextlib import contextmanager


class _FakeUnclosedStore:
    """Stand-in for PgMemoryStore: owns a genuine non-daemon thread that
    only stops when close() runs, mirroring psycopg_pool.ConnectionPool's
    worker thread (issue #398) without needing a live database."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=False)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.01)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


async def _fake_ok_handler(args):  # noqa: ANN001, ARG001 — matches consolidate.handler's signature
    """Stand-in for mcp_server.handlers.consolidate.handler: goes through
    the real _get_store() -> get_shared_store() -> _construct_store() call
    chain (so the real cache/close plumbing is exercised end to end) and
    returns immediately, avoiding a live DB."""
    import mcp_server.handlers.consolidate as consolidate_mod

    consolidate_mod._get_store()
    return {"status": "ok", "duration_ms": 1}


@contextmanager
def _noop_store_lifecycle_cm():
    """Simulates pre-#398-fix behaviour: does nothing on the way out."""
    yield


def _child_main(fixed: bool) -> None:
    """Runs the real consolidate_background module as __main__, inside a
    genuine child process. When ``fixed`` is False, patches
    close_shared_store_on_exit to a no-op first, so the module's own
    lazy import picks up the no-op — reproducing pre-fix behaviour without
    touching the shipped file."""
    from mcp_server.infrastructure import memory_store

    memory_store._construct_store = lambda *a, **k: _FakeUnclosedStore()  # type: ignore[assignment]

    import mcp_server.handlers.consolidate as consolidate_mod

    consolidate_mod.handler = _fake_ok_handler  # noqa: SLF001 — picked up by consolidate_background's lazy `from ... import handler`

    if not fixed:
        import mcp_server.hooks._store_lifecycle as lifecycle_mod

        lifecycle_mod.close_shared_store_on_exit = _noop_store_lifecycle_cm

    runpy.run_module("mcp_server.hooks.consolidate_background", run_name="__main__")


def _run_child(fixed: bool, timeout: float = 3.0) -> tuple[bool, int | None]:
    """Spawn _child_main in a real process; return (reaped_in_time, exitcode)."""
    ctx = multiprocessing.get_context("fork")
    proc = ctx.Process(target=_child_main, args=(fixed,))
    proc.start()
    proc.join(timeout=timeout)
    reaped = not proc.is_alive()
    exitcode = proc.exitcode
    if not reaped:
        proc.terminate()
        proc.join(timeout=1)
    return reaped, exitcode


def test_consolidate_background_hangs_without_the_fix():
    """Reproduces issue #398: with close_shared_store_on_exit neutralized
    (simulating pre-fix behaviour), the unclosed pooled store's non-daemon
    thread keeps the process alive past sys.exit(0) — the failure the bug
    report observed (process still alive, ~98% CPU, 9h after
    'finished status=ok')."""
    reaped, exitcode = _run_child(fixed=False, timeout=3.0)
    assert not reaped, (
        f"process exited on its own without the fix (exitcode={exitcode!r}) "
        "-- the reproduction no longer demonstrates the bug"
    )


def test_consolidate_background_exits_promptly_with_the_fix():
    """issue #398 fix, exercised via the real shipped __main__ block:
    close_shared_store_on_exit closes the pooled store (joining its
    non-daemon thread) before the process ends, so it is reaped well
    within the bound."""
    reaped, exitcode = _run_child(fixed=True, timeout=3.0)
    assert reaped, "process was not reaped within the timeout -- fix regressed"
    assert exitcode == 0
