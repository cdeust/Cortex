"""Child process for scripts/repro_lock_chain.py: one Cortex client.

    python scripts/lock_chain_probe.py <tree> <mode> <url>

``<tree>`` is the root of the Cortex source tree to import (``main``, this
branch, or another install's package), so one experiment can run the
pre-fix and the post-fix code against the same database. Modes:

* ``stream``: open a store, take one chunk of ``iter_memories_for_decay``
  and stop there, as a consolidation consumer does while it works on a
  chunk. On ``write`` from stdin, update that row's importance (the
  consumer's own write); on ``finish``, drain the stream and exit.
* ``open``: open a store (what every hook and server start does), then run
  one read of ``memories``.

Every step prints one line on stdout, flushed, for the parent to wait on.

source: ADR-1112
"""

from __future__ import annotations

import os
import sys


def _say(*words: object) -> None:
    print(*words, flush=True)


def _stream(store) -> None:  # noqa: ANN001 -- the tree's own PgMemoryStore
    chunks = store.iter_memories_for_decay(chunk_size=1)
    first = next(chunks)[0]
    _say("READY", os.getpid())
    for line in sys.stdin:
        if line.strip() == "write":
            store.update_memory_importance(first["id"], 0.5)
            _say("WROTE")
        elif line.strip() == "finish":
            for _ in chunks:
                pass
            _say("DONE")
            return


def main() -> None:
    tree, mode, url = sys.argv[1:4]
    sys.path.insert(0, tree)
    import mcp_server  # noqa: PLC0415 -- resolved from <tree> only after the insert

    _say("TREE", os.path.dirname(os.path.dirname(mcp_server.__file__)))
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 -- same

    try:
        store = PgMemoryStore(database_url=url)
    except Exception as exc:  # noqa: BLE001 -- the outcome is the measurement
        _say("REFUSED", type(exc).__name__)
        return
    _say("OPENED")
    if mode == "stream":
        _stream(store)
    else:
        store._execute("SELECT count(*) FROM memories").fetchone()
        _say("DONE")
    store.close()


if __name__ == "__main__":
    main()
