"""Global test configuration — isolate tests on cortex_test database.

Handler/integration tests hit PostgreSQL when available. When PG is not
available (CI without PG, sandboxed environments), falls back to SQLite
with per-test isolation via temporary DB files.
"""

import importlib
import os
import tempfile

import pytest

# ── Resolve test database URL ─────────────────────────────────────────────

_CURRENT_URL = os.environ.get("DATABASE_URL", "")
_IS_CI = os.environ.get("CI", "").lower() in ("true", "1")

if _IS_CI:
    _TEST_DB_URL = _CURRENT_URL or "postgresql://cortex:cortex@localhost:5432/cortex"
else:
    _TEST_DB_URL = os.environ.get(
        "CORTEX_TEST_DATABASE_URL",
        "postgresql://localhost:5432/cortex_test",
    )

os.environ["DATABASE_URL"] = _TEST_DB_URL


def _pg_available() -> bool:
    """Check if PostgreSQL is reachable."""
    try:
        import psycopg

        conn = psycopg.connect(_TEST_DB_URL, autocommit=True, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


_USE_PG = _pg_available()

# When PG isn't available, force SQLite backend with a temp dir
if not _USE_PG:
    _SQLITE_TEST_DIR = tempfile.mkdtemp(prefix="cortex_test_")
    _sqlite_db = os.path.join(_SQLITE_TEST_DIR, "test.db")
    os.environ["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
    os.environ["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"] = _sqlite_db
    # Handlers pass settings.DB_PATH to MemoryStore(); override it too
    os.environ["CORTEX_MEMORY_DB_PATH"] = _sqlite_db


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
    "schemas",
    "memories",
]


def _get_raw_connection():
    """Get a raw psycopg connection to the test database."""
    if not _USE_PG:
        return None
    try:
        import psycopg

        return psycopg.connect(_TEST_DB_URL, autocommit=True)
    except Exception:
        return None


def _clean_all_tables(conn) -> None:
    """Delete all data from test tables (PostgreSQL)."""
    for table in _TABLES_TO_CLEAN:
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass


_SQLITE_DB_PATH = os.environ.get("CORTEX_MEMORY_SQLITE_FALLBACK_PATH", "")


def _clean_sqlite_via_singleton() -> bool:
    """Clean SQLite tables via an existing handler singleton's connection.

    Returns True if cleanup succeeded (so we don't need a separate connection).
    This avoids 'database is locked' errors from opening a competing connection
    to a WAL-mode SQLite database.
    """
    store_modules = [
        "mcp_server.handlers.recall",
        "mcp_server.handlers.remember",
        "mcp_server.handlers.consolidate",
        "mcp_server.handlers.checkpoint",
        "mcp_server.handlers.memory_stats",
    ]
    for mod_name in store_modules:
        try:
            mod = importlib.import_module(mod_name)
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

    import pkgutil

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


@pytest.fixture(autouse=True)
def _test_isolation():
    """Clean test database and reset singletons between EVERY test.

    This ensures:
    1. Each test starts with empty tables
    2. Handler singletons reconnect fresh
    3. Works with both PostgreSQL and SQLite backends

    Order matters: clean SQLite BEFORE resetting singletons (the store
    reference is needed for cleanup), then reset so next test gets fresh
    connections.
    """
    # Pre-test: clean with existing connections, then reset
    if not _USE_PG:
        _clean_sqlite_store()

    conn = _get_raw_connection()
    if conn:
        _clean_all_tables(conn)

    _reset_all_singletons()

    yield

    # Post-test: clean again, then reset
    if not _USE_PG:
        _clean_sqlite_store()

    _reset_all_singletons()

    if conn:
        try:
            conn.close()
        except Exception:
            pass
