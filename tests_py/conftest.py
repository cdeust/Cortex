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


def _reset_all_singletons() -> None:
    """Reset handler module-level singletons so they reconnect fresh.

    Closes any SQLite store connections before nulling to prevent leaked
    file handles and 'database is locked' errors in subsequent tests.
    """
    modules_and_attrs = [
        ("mcp_server.handlers.recall", ["_store", "_embeddings"]),
        ("mcp_server.handlers.remember", ["_store", "_embeddings"]),
        ("mcp_server.handlers.consolidate", ["_store", "_embeddings"]),
        ("mcp_server.handlers.checkpoint", ["_store"]),
        ("mcp_server.handlers.memory_stats", ["_store"]),
    ]

    # Close any open SQLite store connections before nulling
    closed_ids: set[int] = set()
    for mod_name, attrs in modules_and_attrs:
        try:
            mod = importlib.import_module(mod_name)
            store = getattr(mod, "_store", None)
            if store is not None and id(store) not in closed_ids:
                if hasattr(store, "close"):
                    try:
                        store.close()
                    except Exception:
                        pass
                closed_ids.add(id(store))
        except ImportError:
            pass

    # Now null all singletons
    for mod_name, attrs in modules_and_attrs:
        try:
            mod = importlib.import_module(mod_name)
            for attr in attrs:
                if hasattr(mod, attr):
                    setattr(mod, attr, None)
        except ImportError:
            pass

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
