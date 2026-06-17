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


def _looks_like_test_db(url: str) -> bool:
    """True when the database NAME declares itself a test/bench database."""
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    return name.endswith("_test") or name.endswith("_bench") or "_test_" in name


def _guard_against_populated_db() -> None:
    """Refuse to run destructive test isolation against a populated DB.

    INCIDENT 2026-06-10: an agent ran ``DATABASE_URL=<production> CI=true
    pytest`` — the CI branch above trusted the URL verbatim and
    ``_clean_all_tables`` deleted 537,396 production memories (plus all
    entities, relationships, and prospective triggers) between tests.

    Two-tier guard, fail-closed:
      * a database whose NAME marks it as a test DB (``*_test`` /
        ``*_bench``) is trusted — local cortex_test and bench DBs;
      * any OTHER name (e.g. the fresh runner-local ``cortex`` that real
        CI creates) must hold ZERO memories at session start. A genuine
        test database is created empty; pre-existing rows mean this is
        somebody's real store. No threshold constant — empty is empty.

    Override (explicit, never default): CORTEX_TEST_ALLOW_POPULATED=1.
    """
    if os.environ.get("CORTEX_TEST_ALLOW_POPULATED") == "1":
        return
    if _looks_like_test_db(_TEST_DB_URL):
        return
    try:
        import psycopg

        with psycopg.connect(_TEST_DB_URL, autocommit=True, connect_timeout=3) as conn:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            count = row[0] if row else 0
    except Exception:
        return  # unreachable/uninitialized DB — the SQLite fallback handles it
    if count > 0:
        import pytest

        pytest.exit(
            f"REFUSING to run: test DB '{_TEST_DB_URL}' is not named like a "
            f"test database and already holds {count} memories. The test "
            "suite DELETEs every table between tests — pointing it at a real "
            "store destroys it (incident 2026-06-10: 537k rows lost). Use a "
            "*_test database, or set CORTEX_TEST_ALLOW_POPULATED=1 if you "
            "really mean it.",
            returncode=2,
        )


def _pg_available() -> bool:
    """Check if PostgreSQL is reachable."""
    try:
        import psycopg

        conn = psycopg.connect(_TEST_DB_URL, autocommit=True, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


_guard_against_populated_db()
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

    Uses dynamic discovery over ALL handler modules (pkgutil.iter_modules) so
    that forget, navigate_memory, and any future handler are covered
    automatically.  The prior hardcoded list of 5 modules omitted those two
    handlers, causing the cleanup to fall back to a competing sqlite3.connect()
    whose WAL-mode writes are immediately visible to the handler's still-open
    connection — producing spurious get_memory()==None failures (diagnosed
    2026-06-17, incident test_forget ~30% cold-start flake rate).
    """
    import pkgutil

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
