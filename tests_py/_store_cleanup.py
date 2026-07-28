"""Between-test store cleanup and singleton reset.

Split out of ``conftest.py`` to bring that file back under the 500-line cap
(it had reached 606). Behaviour is unchanged — these are the same functions,
moved verbatim; only the SQLite path binding changed, from conftest's
``_ISOLATED_SQLITE_PATH`` global to the environment variable that global is
built from, so this module has no import cycle back to conftest.

The path is read at import time, exactly as before, and
``_redirect_real_data_roots()`` sets it before any of this is imported —
conftest imports this module below its own redirect call for that reason
(issue #219 ordering constraint).
"""

from __future__ import annotations

import importlib
import os
import pkgutil

# ── Tables to clean between tests (order matters for FK constraints) ─────

_TABLES_TO_CLEAN = [
    "memory_rules",
    "consolidation_log",
    "memory_archives",
    "relationships",
    "entities",
    "prospective_memories",
    "checkpoints",
    "engram_slots",
    "oscillatory_state",
    # A3 scalar homeostatic factor: mcp_server/handlers/consolidate.py
    # unconditionally runs run_homeostatic_cycle(store, None) on every
    # handler() call, so every real-store handler test writes a factor
    # row here. Without this table in the cleanup list that row survives
    # for the rest of the pytest session and can perturb a later test's
    # query that joins homeostatic_state (fetch_member_stats,
    # fetch_contents-adjacent CTEs) — first found via CI run 29109251545
    # (2026-07-10) leaving factor=0.9409 for domain='' cross-test.
    #
    # The domain='' mislabeling itself (streaming scalar branch always
    # resolving _dominant_domain([]) to '' regardless of which domain
    # triggered scaling) was a separate production correctness bug,
    # fixed 2026-07-10 in homeostatic.py (_streaming_health now
    # accumulates real per-domain counts during the same cursor pass).
    # This cleanup entry stays regardless — general test-isolation
    # hygiene, independent of that fix.
    "homeostatic_state",
    "schemas",
    # Receipts before memories: items cascade from receipts, and the hook
    # subprocess tests (test_auto_recall, test_hook_receipts) emit receipts
    # that would otherwise accumulate across runs.
    "injection_receipt_items",
    "injection_receipts",
    "memories",
]


def _clean_all_tables(conn) -> None:
    """Delete all data from test tables (PostgreSQL)."""
    for table in _TABLES_TO_CLEAN:
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass


# Always the throwaway file from _redirect_real_data_roots() — never a path
# inherited from the developer's environment (issue #219).
_SQLITE_DB_PATH = os.environ["CORTEX_MEMORY_DB_PATH"]


def _clean_sqlite_via_singleton() -> bool:
    """Clean SQLite tables via an existing handler singleton's connection.

    Returns True if cleanup succeeded (so we don't need a separate connection).
    This avoids 'database is locked' errors from opening a competing connection
    to a WAL-mode SQLite database.

    Uses dynamic discovery over ALL handler modules (pkgutil.iter_modules) so
    that forget, navigate_memory, and any future handler are covered
    automatically.  The prior hardcoded list of 5 modules omitted those two
    handlers, causing the cleanup to fall back to a competing sqlite3.connect()
    whose WAL-mode writes are immediately visible to the handler's still-open
    connection — producing spurious get_memory()==None failures (diagnosed
    2026-06-17, incident test_forget ~30% cold-start flake rate).
    """

    import mcp_server.handlers as handlers_pkg

    for _finder, mod_name, _ispkg in pkgutil.iter_modules(handlers_pkg.__path__):
        try:
            mod = importlib.import_module(f"mcp_server.handlers.{mod_name}")
            store = getattr(mod, "_store", None)
            if store is not None and hasattr(store, "_conn"):
                conn = store._conn
                for table in _TABLES_TO_CLEAN:
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except Exception:
                        pass
                try:
                    conn.execute("DELETE FROM memories_fts")
                except Exception:
                    pass
                # WAL checkpoint: flush pending writes to main DB file so the
                # next sqlite3.connect() fallback (if it fires) sees a clean
                # slate rather than stale WAL pages.
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
                conn.commit()
                return True
        except Exception:
            pass
    return False


def _clean_sqlite_store() -> None:
    """Clean SQLite tables — prefer singleton connection, fallback to direct."""
    # First try using an existing singleton's connection (avoids DB lock)
    if _clean_sqlite_via_singleton():
        return

    if not _SQLITE_DB_PATH or not os.path.exists(_SQLITE_DB_PATH):
        return
    import sqlite3

    try:
        conn = sqlite3.connect(_SQLITE_DB_PATH, timeout=10)
        for table in _TABLES_TO_CLEAN:
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        try:
            conn.execute("DELETE FROM memories_fts")
        except Exception:
            pass
        # Checkpoint WAL before close so subsequent opens see a clean DB.
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception:
        pass


# Handler module-level caches that hold (a reference to) the shared store or
# its derivatives. Nulling them forces re-fetch from get_shared_store() after
# the shared store is closed; otherwise a handler would hand back a store whose
# psycopg pools are already closed.
_HANDLER_CACHE_ATTRS = ("_store", "_memory_store", "_embeddings", "_memory_available")


def _reset_all_singletons() -> None:
    """Reset the shared store and handler-level caches so the next test
    reconnects fresh.

    The 37 handlers no longer each own a store — they fetch one process-wide
    instance via get_shared_store(), whose two psycopg pools are the only
    connections held. reset_shared_store() closes those pools (fixing the CI
    connection leak that drove live connections past 60 and triggered the
    30-minute batch-pool acquire hangs). We then null every handler cache by
    iterating the handlers package, so the list cannot drift out of date.
    """
    try:
        from mcp_server.infrastructure.memory_store import reset_shared_store

        reset_shared_store()
    except ImportError:
        pass

    import mcp_server.handlers as handlers_pkg

    for _finder, mod_name, _ispkg in pkgutil.iter_modules(handlers_pkg.__path__):
        try:
            mod = importlib.import_module(f"mcp_server.handlers.{mod_name}")
        except Exception:
            continue
        for attr in _HANDLER_CACHE_ATTRS:
            if hasattr(mod, attr):
                # All these caches use None as their "recompute me" sentinel
                # (_memory_available starts None = "not yet checked").
                setattr(mod, attr, None)

    try:
        from mcp_server.infrastructure.memory_config import get_memory_settings

        get_memory_settings.cache_clear()
    except ImportError:
        pass
