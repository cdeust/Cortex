"""Close every process-wide cached store before a one-shot hook exits.

Each ``python -m mcp_server.hooks.*`` invocation is a fresh, short-lived
process. ``mcp_server.infrastructure.memory_store.get_shared_store`` caches
constructed stores in a module-global dict (``_shared_stores``) so the
*long-lived* MCP server process reuses one pooled connection across many
handler calls — but a one-shot hook process never comes back to reuse that
cache; it constructs exactly one store, uses it once, and should exit.

``PgMemoryStore`` owns two psycopg ``ConnectionPool`` instances, each with a
non-daemon worker thread (issue #398). Left open, ``sys.exit()`` cannot end
the process: the interpreter waits for the non-daemon thread, and on Python
3.14 ``ConnectionPool.__del__`` racing finalization raises
``PythonFinalizationError`` instead of joining cleanly — the process spins
forever instead of exiting. ``PgMemoryStore.close()`` (pg_store.py) already
closes both pools correctly; the missing piece was ever calling it from a
one-shot hook process.

Use as::

    with close_shared_store_on_exit():
        main()

wrapping the hook's entire entry-point call so every exit path — a normal
return, a raised exception, or ``sys.exit()`` (which raises ``SystemExit``,
still caught by a ``finally``) — closes the store before the process ends.

This module has zero dependencies beyond the standard library at import
time (the store import is deferred inside the context manager), matching
``_headless_guard.py``'s contract that importing a hook helper can never
fail for a missing third-party package.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def close_shared_store_on_exit() -> Iterator[None]:
    """Close every process-wide cached store on the way out, success or not.

    precondition: none — safe to call even if no store was ever constructed
    in this process (``reset_shared_store`` no-ops on an empty cache).
    postcondition: every store in ``memory_store._shared_stores`` has had
    ``close()`` called and the cache is empty, regardless of whether the
    wrapped block returned normally, raised, or called ``sys.exit()``.
    invariant: teardown failure never masks the wrapped block's own outcome
    — ``reset_shared_store`` already swallows and logs a per-store close
    error (memory_store.py), and this context manager does not re-raise.
    """
    try:
        yield
    finally:
        from mcp_server.infrastructure.memory_store import (  # noqa: PLC0415 — deferred: keep this module import-safe with zero third-party deps
            reset_shared_store,
        )

        try:
            reset_shared_store()
        except Exception:  # noqa: BLE001 — teardown boundary: must never mask the hook's own outcome
            logger.debug(
                "reset_shared_store failed during hook teardown", exc_info=True
            )
