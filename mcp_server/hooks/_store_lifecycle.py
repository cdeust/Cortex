"""Close every process-wide cached store before a one-shot hook exits.

Each ``python -m mcp_server.hooks.*`` invocation is a fresh, short-lived
process. ``mcp_server.infrastructure.memory_store.get_shared_store`` caches
constructed stores in a module-global dict (``_shared_stores``) so the
*long-lived* MCP server process reuses one pooled connection across many
handler calls — but a one-shot hook process never comes back to reuse that
cache; it constructs exactly one store, uses it once, and should exit.

``PgMemoryStore`` owns two psycopg ``ConnectionPool`` instances (issue
#398). What is established, verified against the exact ``psycopg-pool``
version this project pins (3.3.1, ``uv.lock``, wheel sha256
``2af5b432941c4c9ad5c87b3fa410aec910ec8f7c122855897983a06c45f2e4b5``,
downloaded and read directly): every pool worker/scheduler thread is
created with ``daemon=True`` (``psycopg_pool/_acompat.py::spawn``) —
*not* non-daemon, correcting an earlier (wrong) draft of this note.
``ConnectionPool.__del__`` (``pool.py:118-126``) calls ``gather()``,
which calls ``thread.join(timeout=5.0)`` on those daemon threads,
whenever the pool is garbage-collected without ``close()`` ever having
run. On Python 3.14, joining a thread this late during interpreter
finalization raises ``PythonFinalizationError: cannot join thread at
interpreter shutdown`` — the exact traceback issue #398 reports.

What is **not** established: why this correlates with the reported
~9-hour, ~98%-CPU-spin observation. Daemon threads cannot, by
definition, block ordinary process exit, and CPython treats an
exception raised inside ``__del__`` during shutdown as "ignored"
(printed to stderr, non-fatal) rather than blocking. The mechanism
connecting the logged ``PythonFinalizationError`` to the extended spin
was not reproduced live under Python 3.14 for this fix and is not
claimed here.

What the fix does regardless of that open question: ``close()``
(``pool.py:427-442``) sets ``self._closed = True`` *before* it runs the
same ``gather()``/``join()`` — but while the interpreter is still fully
alive, not during finalization. Once ``_closed`` is ``True``,
``__del__``'s own early-return guard
(``if getattr(self, "_closed", True): return``, ``pool.py:120-121``)
fires immediately and the fragile finalization-time join never runs at
all. Calling ``PgMemoryStore.close()`` (pg_store.py, which already
closes both pools correctly) from a one-shot hook process closes the
exact code path the issue's traceback shows firing — independent of
whatever the full causal chain to the reported CPU spin turns out to
be.

Use as::

    with close_shared_store_on_exit():
        main()

wrapping the hook's entire entry-point call so every exit path — a normal
return, a raised exception, or ``sys.exit()`` (which raises ``SystemExit``,
still caught by a ``finally``) — closes the store before the process ends.

This module has zero dependencies beyond the standard library at import
time and teardown never imports a store that was not loaded, matching
``_headless_guard.py``'s contract that importing a hook helper can never
fail for a missing third-party package.
"""

from __future__ import annotations

import logging
import sys
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
        try:
            # No loaded factory means no process-wide store cache to close.
            # source: Python import reference §5.3.1 (sys.modules cache).
            module = sys.modules.get("mcp_server.infrastructure.memory_store")
            if module is not None:
                module.reset_shared_store()
        except Exception:  # noqa: BLE001 — teardown boundary: must never mask the hook's own outcome
            logger.debug(
                "reset_shared_store failed during hook teardown", exc_info=True
            )
