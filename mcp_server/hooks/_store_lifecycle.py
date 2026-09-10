"""Close every process-wide cached store before a one-shot hook exits.

Each ``python -m mcp_server.hooks.*`` invocation is a fresh, short-lived
process. ``mcp_server.infrastructure.memory_store.get_shared_store`` caches
constructed stores in a module-global dict (``_shared_stores``) so the
*long-lived* MCP server process reuses one pooled connection across many
handler calls — but a one-shot hook process never comes back to reuse that
cache; it constructs exactly one store, uses it once, and should exit.

Use as::

    with close_shared_store_on_exit():
        main()

wrapping the hook's entire entry-point call so every exit path — a normal
return, a raised exception, or ``sys.exit()`` (which raises ``SystemExit``,
still caught by a ``finally``) — closes the store before the process ends.

source: ADR-0479"""

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
            # source: ADR-0479
            module = sys.modules.get("mcp_server.infrastructure.memory_store")
            if module is not None:
                module.reset_shared_store()
        except Exception:  # noqa: BLE001 — teardown boundary: must never mask the hook's own outcome
            logger.debug(
                "reset_shared_store failed during hook teardown", exc_info=True
            )
