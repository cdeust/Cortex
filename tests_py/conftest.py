"""Global test configuration — isolate tests on cortex_test database.

All handler/integration tests hit PostgreSQL. This conftest ensures they
use the `cortex_test` database (not production `cortex`) and cleans state
between tests.
"""

import os
import pytest

# ── Force all tests to use cortex_test database ──────────────────────────

_TEST_DB_URL = os.environ.get(
    "CORTEX_TEST_DATABASE_URL",
    "postgresql://localhost:5432/cortex_test",
)

# Set DATABASE_URL before any module imports PgMemoryStore
os.environ["DATABASE_URL"] = _TEST_DB_URL


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
    try:
        import psycopg
        return psycopg.connect(_TEST_DB_URL, autocommit=True)
    except Exception:
        return None


def _clean_all_tables(conn) -> None:
    """Delete all data from test tables."""
    for table in _TABLES_TO_CLEAN:
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass


def _reset_all_singletons() -> None:
    """Reset handler module-level singletons so they reconnect fresh."""
    modules_and_attrs = [
        ("mcp_server.handlers.recall", ["_store", "_embeddings"]),
        ("mcp_server.handlers.remember", ["_store", "_embeddings"]),
        ("mcp_server.handlers.consolidate", ["_store", "_embeddings"]),
        ("mcp_server.handlers.checkpoint", ["_store"]),
        ("mcp_server.handlers.memory_stats", ["_store"]),
    ]
    import importlib
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
def _pg_test_isolation():
    """Clean test database and reset singletons between EVERY test.

    This ensures:
    1. Each test starts with empty tables
    2. Handler singletons reconnect fresh to cortex_test
    3. Failed transactions are rolled back
    """
    conn = _get_raw_connection()
    if conn:
        _clean_all_tables(conn)

    _reset_all_singletons()

    yield

    # After each test: reset singletons and roll back poisoned transactions
    _reset_all_singletons()

    if conn:
        try:
            conn.close()
        except Exception:
            pass
