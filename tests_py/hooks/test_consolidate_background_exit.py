"""Verifies the fix for issue #398: consolidate_background must call
close() on its pooled store before the one-shot process exits.

Correction (2026-08-10, PR #417 review): an earlier version of this file
claimed the pool's worker threads were non-daemon and that this test
reproduced a process hang. Both claims were false. Verified directly
against the pinned dependency (psycopg-pool==3.3.1, uv.lock; wheel
downloaded and its sha256 checked against the lock file's pin;
``psycopg_pool/_acompat.py::spawn`` creates every worker/scheduler thread
with ``daemon=True``). Daemon threads cannot, by definition, block a
process from exiting, so a test asserting "the process hangs without the
fix" was not exercising a real defect.

What IS established (source: the same downloaded, hash-verified wheel):
``ConnectionPool.__del__`` (``pool.py:118-126``) early-returns if
``self._closed`` is already true (``pool.py:120-121``); otherwise it calls
``gather()`` -> ``thread.join(timeout=5.0)`` on the (daemon) worker
threads. ``close()`` (``pool.py:427-442``) sets ``_closed = True`` before
running that same join -- but while the interpreter is still alive, not
during finalization -- so calling it up front means ``__del__`` will
always take the early-return branch later, whenever the interpreter
actually collects the object. That is the mechanism this fix relies on
and the one this test exercises: **close() is called before the process
exits, on every path**. What remains unestablished (see
``mcp_server/hooks/_store_lifecycle.py`` for the full account) is why an
unclosed pool was observed to correlate with a ~9-hour, ~98%-CPU spin in
production -- that causal chain is not claimed or tested here.
"""

from __future__ import annotations

import multiprocessing
import runpy
from contextlib import contextmanager


class _FakeStore:
    """Stand-in for PgMemoryStore. Models the one mechanism verified
    against the pinned psycopg-pool source: __del__ raises unless close()
    already set a "closed" flag -- a direct model of the
    early-return-vs-raise branch in ConnectionPool.__del__ (pool.py:120-121
    vs :126), not a claim about thread daemon status or hang duration."""

    def __init__(self, close_called) -> None:  # noqa: ANN001 -- multiprocessing.Value, not picklable-friendly to annotate across fork
        self._closed = False
        self._close_called = close_called

    def close(self) -> None:
        self._closed = True
        self._close_called.value = 1

    def __del__(self) -> None:
        if not self._closed:
            # Mirrors ConnectionPool.__del__ taking the gather()/join()
            # branch instead of the early return -- the branch that, on
            # Python 3.14, can raise PythonFinalizationError during
            # interpreter finalization (issue #398's exact traceback).
            # CPython treats a __del__ exception at shutdown as "ignored"
            # (printed, non-fatal) -- this does not, by itself, hang the
            # process; it demonstrates the fragile branch, nothing more.
            raise RuntimeError("simulated: cannot join thread at interpreter shutdown")


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


def _child_main(fixed: bool, close_called) -> None:  # noqa: ANN001 -- multiprocessing.Value
    """Runs the real consolidate_background module as __main__, inside a
    genuine child process. When ``fixed`` is False, patches
    close_shared_store_on_exit to a no-op first, so the module's own
    lazy import picks up the no-op — reproducing pre-fix behaviour without
    touching the shipped file."""
    from mcp_server.infrastructure import memory_store

    memory_store._construct_store = lambda *a, **k: _FakeStore(close_called)  # type: ignore[assignment]

    import mcp_server.handlers.consolidate as consolidate_mod

    consolidate_mod.handler = _fake_ok_handler  # noqa: SLF001 — picked up by consolidate_background's lazy `from ... import handler`

    if not fixed:
        import mcp_server.hooks._store_lifecycle as lifecycle_mod

        lifecycle_mod.close_shared_store_on_exit = _noop_store_lifecycle_cm

    try:
        runpy.run_module("mcp_server.hooks.consolidate_background", run_name="__main__")
    except SystemExit:
        pass  # main()'s own sys.exit(); multiprocessing reports the process exit code


def _run_child(fixed: bool, timeout: float = 5.0) -> tuple[bool, bool]:
    """Spawn _child_main in a real process.

    Returns (reaped_in_time, close_was_called). Reaping is asserted as a
    sanity check only (both cases are expected to exit promptly -- daemon
    threads do not block exit); the load-bearing assertion is
    close_was_called.
    """
    ctx = multiprocessing.get_context("fork")
    close_called = ctx.Value("i", 0)
    proc = ctx.Process(target=_child_main, args=(fixed, close_called))
    proc.start()
    proc.join(timeout=timeout)
    reaped = not proc.is_alive()
    if not reaped:
        proc.terminate()
        proc.join(timeout=1)
    return reaped, bool(close_called.value)


def test_consolidate_background_does_not_close_store_without_the_fix():
    """Simulates pre-#398-fix wiring (close_shared_store_on_exit
    neutralized): the store's close() is never called, leaving the
    fragile __del__ path armed."""
    reaped, closed = _run_child(fixed=False)
    assert reaped, "sanity check: even the unfixed simulation should exit promptly"
    assert not closed, (
        "close() was called even with the fix neutralized -- the "
        "reproduction no longer demonstrates the pre-fix gap"
    )


def test_consolidate_background_closes_store_with_the_fix():
    """issue #398 fix, exercised via the real shipped __main__ block:
    close_shared_store_on_exit calls close() on the pooled store before
    the process ends, on every exit path."""
    reaped, closed = _run_child(fixed=True)
    assert reaped
    assert closed, "close() was not called -- fix regressed"
